"""Permission-checked mail portal backed by the shared Supabase database.

The browser receives no Supabase service key. Access to mailbox and message data
is restricted by the FastAPI admin authorization dependency. Provider keys remain
server-side and outbound messages are mirrored into email_messages/recipients.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, EmailStr, Field

from core.config import settings
from ADMINS.auth.dependencies import require_permission

router = APIRouter(prefix="/mail", tags=["Mail Portal"])

MESSAGE_FIELDS = (
    "email_message_id,mailbox_id,thread_id,direction,status,message_id,in_reply_to,"
    "references_header,from_address,from_name,subject,text_body,html_body,is_read,"
    "is_starred,is_important,sent_at,received_at,created_at,updated_at,deleted_at,"
    "resend_email_id,resend_event_id,folder,snippet,snoozed_until,"
    "email_recipients(email_address,display_name,recipient_type)"
)
MESSAGE_LIST_FIELDS = (
    "email_message_id,mailbox_id,thread_id,direction,status,from_address,from_name,"
    "subject,is_read,is_starred,is_important,sent_at,received_at,created_at,deleted_at,"
    "folder,snippet,snoozed_until,"
    "email_recipients(email_address,display_name,recipient_type)"
)


class MailPayload(BaseModel):
    mailbox_id: int = Field(ge=1)
    to: list[EmailStr] = Field(default_factory=list, max_length=100)
    cc: list[EmailStr] = Field(default_factory=list, max_length=100)
    bcc: list[EmailStr] = Field(default_factory=list, max_length=100)
    reply_to: EmailStr | None = None
    subject: str = Field(default="", max_length=998)
    body_text: str | None = Field(default=None, max_length=1_000_000)
    body_html: str | None = Field(default=None, max_length=1_000_000)
    thread_id: int | None = Field(default=None, ge=1)
    in_reply_to: str | None = Field(default=None, max_length=998)


def _headers(prefer: str | None = None) -> dict[str, str]:
    url, key = settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY
    if not url or not key:
        raise HTTPException(
            status_code=503,
            detail="Mail database access is not configured on the server",
        )
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    return headers


async def _supa(
    method: str,
    resource: str,
    *,
    params: dict | None = None,
    payload=None,
    prefer: str | None = None,
):
    base = (settings.SUPABASE_URL or "").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=18.0) as client:
            response = await client.request(
                method,
                f"{base}/rest/v1/{resource}",
                headers=_headers(prefer),
                params=params,
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Mail database service is temporarily unavailable") from exc

    if not response.is_success:
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Mail record not found")
        if response.status_code in (401, 403):
            raise HTTPException(status_code=403, detail="Mail database access was denied")
        if response.status_code == 409:
            raise HTTPException(status_code=409, detail="Mail update conflicted with current data")
        raise HTTPException(status_code=502, detail="Mail database request failed")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Mail database returned an invalid response") from exc


def _decorate(row: dict, *, detailed: bool = False) -> dict:
    result = dict(row)
    result["id"] = result.get("email_message_id")
    result["body_text"] = result.pop("text_body", None)
    result["body_html"] = result.pop("html_body", None)
    recipients = result.pop("email_recipients", []) or []
    tos = [r.get("email_address") for r in recipients if r.get("recipient_type") == "to"]
    ccs = [r.get("email_address") for r in recipients if r.get("recipient_type") == "cc"]
    bccs = [r.get("email_address") for r in recipients if r.get("recipient_type") == "bcc"]
    result["to_address"] = ", ".join(x for x in tos if x)
    result["cc_address"] = ", ".join(x for x in ccs if x)
    result["bcc_address"] = ", ".join(x for x in bccs if x)
    result["recipients"] = recipients if detailed else None
    if result.get("snippet") is None:
        body = result.get("body_text") or ""
        result["snippet"] = re.sub(r"\s+", " ", body).strip()[:180]
    return result


async def _mailbox(mailbox_id: int, *, for_sending: bool = False) -> dict:
    rows = await _supa(
        "GET",
        "mailboxes",
        params={
            "select": "mailbox_id,email_address,display_name,is_active,is_receiving_enabled,is_sending_enabled",
            "mailbox_id": f"eq.{mailbox_id}",
            "limit": "1",
        },
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    mailbox = rows[0]
    if not mailbox.get("is_active"):
        raise HTTPException(status_code=403, detail="Mailbox is inactive")
    if for_sending and not mailbox.get("is_sending_enabled"):
        raise HTTPException(status_code=403, detail="Sending is disabled for this mailbox")
    if not for_sending and not mailbox.get("is_receiving_enabled"):
        # Still permit sent/draft/archived operations; this flag only blocks inbox refresh.
        pass
    mailbox["id"] = mailbox.get("mailbox_id")
    mailbox["email"] = mailbox.get("email_address")
    mailbox["name"] = mailbox.get("display_name") or mailbox.get("email_address")
    return mailbox


async def _list_messages(mailbox_id: int, folder: str, limit: int = 100, offset: int = 0, search: str | None = None) -> list[dict]:
    params = {
        "select": MESSAGE_LIST_FIELDS,
        "mailbox_id": f"eq.{mailbox_id}",
        "order": "received_at.desc.nullslast,created_at.desc",
        "limit": str(max(1, min(limit, 200))),
        "offset": str(max(0, offset)),
    }
    if folder == "inbox":
        params.update({"folder": "eq.inbox", "deleted_at": "is.null"})
    elif folder == "sent":
        params.update({"folder": "eq.sent", "deleted_at": "is.null"})
    elif folder == "starred":
        params.update({"is_starred": "eq.true", "deleted_at": "is.null"})
    elif folder == "archive":
        params.update({"folder": "eq.archive", "deleted_at": "is.null"})
    elif folder == "trash":
        params["folder"] = "eq.trash"
    elif folder == "drafts":
        params.update({"folder": "eq.drafts", "status": "eq.draft", "deleted_at": "is.null"})
    if search:
        q = re.sub(r"[^a-zA-Z0-9 @._+-]", " ", search).strip()[:120]
        if q:
            pattern = f"*{q}*"
            params["or"] = f"(subject.ilike.{pattern},from_address.ilike.{pattern},text_body.ilike.{pattern},snippet.ilike.{pattern})"
    rows = await _supa("GET", "email_messages", params=params)
    return [_decorate(row) for row in rows or []]


@router.get("/mailboxes")
async def list_mailboxes(admin=Depends(require_permission("products.read"))):
    rows = await _supa(
        "GET",
        "mailboxes",
        params={
            "select": "mailbox_id,email_address,display_name,mailbox_type,is_active,is_receiving_enabled,is_sending_enabled",
            "is_active": "eq.true",
            "order": "display_name.asc,email_address.asc",
            "limit": "200",
        },
    )
    return [
        {
            **row,
            "id": row.get("mailbox_id"),
            "email": row.get("email_address"),
            "name": row.get("display_name") or row.get("email_address"),
        }
        for row in rows or []
    ]


@router.get("/inbox/{mailbox_id}")
async def inbox(mailbox_id: int = Path(ge=1), limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0), admin=Depends(require_permission("products.read"))):
    await _mailbox(mailbox_id)
    return await _list_messages(mailbox_id, "inbox", limit, offset)


@router.get("/outbox/{mailbox_id}")
async def outbox(mailbox_id: int = Path(ge=1), limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0), admin=Depends(require_permission("products.read"))):
    await _mailbox(mailbox_id)
    return await _list_messages(mailbox_id, "sent", limit, offset)


@router.get("/starred/{mailbox_id}")
async def starred(mailbox_id: int = Path(ge=1), limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0), admin=Depends(require_permission("products.read"))):
    await _mailbox(mailbox_id)
    return await _list_messages(mailbox_id, "starred", limit, offset)


@router.get("/archived/{mailbox_id}")
async def archived(mailbox_id: int = Path(ge=1), limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0), admin=Depends(require_permission("products.read"))):
    await _mailbox(mailbox_id)
    return await _list_messages(mailbox_id, "archive", limit, offset)


@router.get("/trash/{mailbox_id}")
async def trash(mailbox_id: int = Path(ge=1), limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0), admin=Depends(require_permission("products.read"))):
    await _mailbox(mailbox_id)
    return await _list_messages(mailbox_id, "trash", limit, offset)


@router.get("/drafts/{mailbox_id}")
async def drafts(mailbox_id: int = Path(ge=1), limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0), admin=Depends(require_permission("products.read"))):
    await _mailbox(mailbox_id)
    return await _list_messages(mailbox_id, "drafts", limit, offset)


@router.get("/search/{mailbox_id}")
async def search(mailbox_id: int = Path(ge=1), q: str = Query(min_length=1, max_length=120), limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0), admin=Depends(require_permission("products.read"))):
    await _mailbox(mailbox_id)
    return await _list_messages(mailbox_id, "all", limit, offset, q)


@router.get("/messages/{email_id}")
async def message(email_id: int = Path(ge=1), admin=Depends(require_permission("products.read"))):
    rows = await _supa(
        "GET", "email_messages",
        params={"select": MESSAGE_FIELDS, "email_message_id": f"eq.{email_id}", "limit": "1"},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Message not found")
    return _decorate(rows[0], detailed=True)


def _recipient_rows(message_id: int, values: list[EmailStr], kind: Literal["to", "cc", "bcc"]) -> list[dict]:
    return [
        {
            "email_message_id": message_id,
            "recipient_type": kind,
            "email_address": str(email).strip().lower(),
        }
        for email in values
    ]


async def _insert_recipients(message_id: int, payload: MailPayload) -> None:
    rows = (
        _recipient_rows(message_id, payload.to, "to")
        + _recipient_rows(message_id, payload.cc, "cc")
        + _recipient_rows(message_id, payload.bcc, "bcc")
    )
    if rows:
        await _supa("POST", "email_recipients", payload=rows, prefer="return=minimal")


@router.post("/drafts", status_code=201)
async def create_draft(payload: MailPayload, admin=Depends(require_permission("products.write"))):
    mailbox = await _mailbox(payload.mailbox_id)
    if not payload.subject.strip() and not (payload.body_text or "").strip() and not (payload.body_html or "").strip():
        raise HTTPException(status_code=422, detail="A draft needs a subject or message body")
    rows = await _supa(
        "POST", "email_messages",
        payload={
            "mailbox_id": payload.mailbox_id,
            "direction": "outbound",
            "status": "draft",
            "folder": "drafts",
            "from_address": mailbox["email_address"],
            "from_name": mailbox.get("name"),
            "subject": payload.subject.strip(),
            "text_body": payload.body_text,
            "html_body": payload.body_html,
            "is_read": True,
            "is_starred": False,
            "snippet": re.sub(r"\s+", " ", payload.body_text or "").strip()[:180],
            "thread_id": payload.thread_id,
            "in_reply_to": payload.in_reply_to,
        },
        prefer="return=representation",
    )
    if not rows:
        raise HTTPException(status_code=502, detail="Could not save the draft")
    message_id = int(rows[0]["email_message_id"])
    await _insert_recipients(message_id, payload)
    return {"database_email_id": message_id, "status": "draft"}


@router.post("/send", status_code=201)
async def send_email(payload: MailPayload, admin=Depends(require_permission("products.write"))):
    if not payload.to:
        raise HTTPException(status_code=422, detail="At least one recipient is required")
    if not payload.subject.strip():
        raise HTTPException(status_code=422, detail="Subject is required")
    if not (payload.body_text or "").strip() and not (payload.body_html or "").strip():
        raise HTTPException(status_code=422, detail="Email body is required")
    if not settings.RESEND_API_KEY:
        raise HTTPException(status_code=503, detail="Outbound mail provider is not configured on the server")
    mailbox = await _mailbox(payload.mailbox_id, for_sending=True)
    from_name = settings.RESEND_FROM_NAME or mailbox.get("name") or "RT Crackers"
    from_address = f"{from_name} <{mailbox['email_address']}>"

    created = await _supa(
        "POST", "email_messages",
        payload={
            "mailbox_id": payload.mailbox_id,
            "direction": "outbound",
            "status": "queued",
            "folder": "sent",
            "from_address": mailbox["email_address"],
            "from_name": from_name,
            "subject": payload.subject.strip(),
            "text_body": payload.body_text,
            "html_body": payload.body_html,
            "is_read": True,
            "is_starred": False,
            "snippet": re.sub(r"\s+", " ", payload.body_text or "").strip()[:180],
            "thread_id": payload.thread_id,
            "in_reply_to": payload.in_reply_to,
        },
        prefer="return=representation",
    )
    if not created:
        raise HTTPException(status_code=502, detail="Could not create the outbound mail record")
    message_id = int(created[0]["email_message_id"])
    try:
        await _insert_recipients(message_id, payload)
        request_json = {
            "from": from_address,
            "to": [str(email).lower() for email in payload.to],
            "subject": payload.subject.strip(),
        }
        if payload.cc:
            request_json["cc"] = [str(email).lower() for email in payload.cc]
        if payload.bcc:
            request_json["bcc"] = [str(email).lower() for email in payload.bcc]
        if payload.reply_to:
            request_json["reply_to"] = str(payload.reply_to).lower()
        if payload.body_text:
            request_json["text"] = payload.body_text
        if payload.body_html:
            request_json["html"] = payload.body_html
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}", "Content-Type": "application/json"},
                json=request_json,
            )
        if not response.is_success:
            await _supa(
                "PATCH", "email_messages",
                params={"email_message_id": f"eq.{message_id}"},
                payload={"status": "failed", "updated_at": datetime.now(timezone.utc).isoformat()},
                prefer="return=minimal",
            )
            raise HTTPException(status_code=502, detail="The mail provider could not send this message")
        provider = response.json()
        provider_id = provider.get("id")
        await _supa(
            "PATCH", "email_messages",
            params={"email_message_id": f"eq.{message_id}"},
            payload={
                "status": "sent",
                "resend_email_id": provider_id,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            prefer="return=minimal",
        )
        return {"database_email_id": message_id, "resend_email_id": provider_id, "status": "sent"}
    except HTTPException:
        raise
    except Exception as exc:
        # The database row remains and makes provider/delivery problems auditable.
        await _supa(
            "PATCH", "email_messages",
            params={"email_message_id": f"eq.{message_id}"},
            payload={"status": "failed", "updated_at": datetime.now(timezone.utc).isoformat()},
            prefer="return=minimal",
        )
        raise HTTPException(status_code=502, detail="Mail send failed; the message is recorded as failed") from exc


async def _set_message_flag(email_id: int, payload: dict):
    rows = await _supa(
        "PATCH", "email_messages",
        params={"email_message_id": f"eq.{email_id}"},
        payload={**payload, "updated_at": datetime.now(timezone.utc).isoformat()},
        prefer="return=representation",
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"ok": True}


@router.post("/messages/{email_id}/read")
async def mark_read(email_id: int = Path(ge=1), admin=Depends(require_permission("products.write"))):
    return await _set_message_flag(email_id, {"is_read": True})


@router.post("/messages/{email_id}/unread")
async def mark_unread(email_id: int = Path(ge=1), admin=Depends(require_permission("products.write"))):
    return await _set_message_flag(email_id, {"is_read": False})


@router.post("/messages/{email_id}/star")
async def star_message(email_id: int = Path(ge=1), admin=Depends(require_permission("products.write"))):
    return await _set_message_flag(email_id, {"is_starred": True})


@router.post("/messages/{email_id}/unstar")
async def unstar_message(email_id: int = Path(ge=1), admin=Depends(require_permission("products.write"))):
    return await _set_message_flag(email_id, {"is_starred": False})


@router.post("/messages/{email_id}/archive")
async def archive_message(email_id: int = Path(ge=1), admin=Depends(require_permission("products.write"))):
    return await _set_message_flag(email_id, {"folder": "archive", "deleted_at": None})


@router.post("/messages/{email_id}/unarchive")
async def unarchive_message(email_id: int = Path(ge=1), admin=Depends(require_permission("products.write"))):
    rows = await _supa("GET", "email_messages", params={"select": "direction", "email_message_id": f"eq.{email_id}", "limit": "1"})
    if not rows:
        raise HTTPException(status_code=404, detail="Message not found")
    folder = "sent" if rows[0].get("direction") == "outbound" else "inbox"
    return await _set_message_flag(email_id, {"folder": folder, "deleted_at": None})


@router.post("/messages/{email_id}/trash")
async def trash_message(email_id: int = Path(ge=1), admin=Depends(require_permission("products.write"))):
    return await _set_message_flag(email_id, {"folder": "trash", "deleted_at": datetime.now(timezone.utc).isoformat()})


@router.post("/messages/{email_id}/restore")
async def restore_message(email_id: int = Path(ge=1), admin=Depends(require_permission("products.write"))):
    rows = await _supa("GET", "email_messages", params={"select": "direction", "email_message_id": f"eq.{email_id}", "limit": "1"})
    if not rows:
        raise HTTPException(status_code=404, detail="Message not found")
    folder = "sent" if rows[0].get("direction") == "outbound" else "inbox"
    return await _set_message_flag(email_id, {"folder": folder, "deleted_at": None})
    if folder != "trash":
        params["deleted_at"] = "is.null"


def _verify_resend_signature(raw: bytes, webhook_id: str, timestamp: str, signature: str) -> bool:
    import base64
    import hashlib
    import hmac
    import time

    secret = settings.RESEND_WEBHOOK_SECRET
    if not secret or not webhook_id or not timestamp or not signature:
        return False
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - sent_at) > 300:
        return False
    signing_secret = secret.removeprefix("whsec_")
    try:
        key = base64.b64decode(signing_secret + "=" * (-len(signing_secret) % 4))
    except (ValueError, TypeError):
        return False
    signed = webhook_id.encode() + b"." + timestamp.encode() + b"." + raw
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    candidates = []
    for part in signature.split():
        if "," not in part:
            continue
        version, _, value = part.partition(",")
        if version == "v1":
            candidates.append(value)
    return any(hmac.compare_digest(expected, candidate) for candidate in candidates)


@router.post("/webhook/resend")
async def resend_webhook(request: Request):
    """Receive verified Resend delivery and inbound-email events. Configure this URL in Resend."""
    import json
    from email.utils import parseaddr

    raw = await request.body()
    webhook_id = request.headers.get("svix-id", "")
    timestamp = request.headers.get("svix-timestamp", "")
    signature = request.headers.get("svix-signature", "")
    if not _verify_resend_signature(raw, webhook_id, timestamp, signature):
        raise HTTPException(status_code=400, detail="Invalid or expired mail webhook signature")
    try:
        event = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook JSON") from exc
    if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
        raise HTTPException(status_code=400, detail="Invalid webhook event")

    # Idempotency: Resend/Svix reuses a webhook ID on retries.
    duplicate = await _supa(
        "GET", "email_messages",
        params={"select": "email_message_id", "resend_event_id": f"eq.{webhook_id}", "limit": "1"},
    )
    if duplicate:
        return {"ok": True, "duplicate": True}

    event_type = str(event.get("type") or "")
    data = event["data"]
    email_id = str(data.get("email_id") or data.get("id") or "")
    if event_type in {"email.delivered", "email.bounced", "email.complained", "email.failed", "email.sent"}:
        if not email_id:
            return {"ok": True, "ignored": True}
        status_by_type = {
            "email.delivered": "delivered",
            "email.bounced": "bounced",
            "email.complained": "complained",
            "email.failed": "failed",
            "email.sent": "sent",
        }
        await _supa(
            "PATCH", "email_messages",
            params={"resend_email_id": f"eq.{email_id}"},
            payload={
                "status": status_by_type[event_type],
                "resend_event_id": webhook_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            prefer="return=minimal",
        )
        return {"ok": True}

    if event_type != "email.received":
        return {"ok": True, "ignored": True}
    if not email_id:
        raise HTTPException(status_code=422, detail="Inbound event has no email ID")
    if not settings.RESEND_API_KEY:
        raise HTTPException(status_code=503, detail="Inbound mail provider is not configured")

    # Resend's event gives recipient and message metadata. Retrieve the full
    # body from the receiving API; no body is trusted from a browser request.
    try:
        async with httpx.AsyncClient(timeout=18.0) as client:
            received_response = await client.get(
                "https://api.resend.com/emails/receiving/" + email_id,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}", "Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Could not retrieve the received email") from exc
    if not received_response.is_success:
        raise HTTPException(status_code=502, detail="The inbound email body could not be retrieved")
    try:
        received_payload = received_response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Invalid inbound email response") from exc
    received = received_payload.get("data", received_payload) if isinstance(received_payload, dict) else {}
    recipients = data.get("to") or received.get("to") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    mailboxes = []
    for recipient in recipients:
        address = parseaddr(str(recipient))[1].lower().strip()
        if not address:
            continue
        matches = await _supa(
            "GET", "mailboxes",
            params={
                "select": "mailbox_id,email_address,display_name,is_active,is_receiving_enabled",
                "email_address": f"eq.{address}",
                "is_active": "eq.true",
                "is_receiving_enabled": "eq.true",
                "limit": "1",
            },
        )
        if matches:
            mailboxes.append((matches[0], address))
    if not mailboxes:
        # An unprovisioned recipient should not cause endless provider retries.
        return {"ok": True, "ignored": True, "reason": "No active receiving mailbox matched the recipient"}

    mailbox = mailboxes[0][0]
    from_raw = str(received.get("from") or data.get("from") or "")
    from_name, from_address = parseaddr(from_raw)
    from_address = (from_address or from_raw).lower()[:254]
    subject = str(received.get("subject") or data.get("subject") or "(no subject)")[:998]
    body_text = received.get("text") or received.get("text_body")
    body_html = received.get("html") or received.get("html_body")
    body_text = str(body_text)[:1_000_000] if body_text is not None else None
    body_html = str(body_html)[:1_000_000] if body_html is not None else None
    snippet_source = body_text or re.sub(r"<[^>]+>", " ", body_html or "")
    snippet = re.sub(r"\\s+", " ", snippet_source).strip()[:180]
    message_id = str(received.get("message_id") or data.get("message_id") or "")[:998] or None
    existing = await _supa(
        "GET", "email_messages",
        params={"select": "email_message_id", "message_id": f"eq.{message_id}", "mailbox_id": f"eq.{mailbox['mailbox_id']}", "limit": "1"},
    ) if message_id else []
    if existing:
        await _supa(
            "PATCH", "email_messages",
            params={"email_message_id": f"eq.{existing[0]['email_message_id']}"},
            payload={"resend_event_id": webhook_id, "resend_email_id": email_id, "updated_at": datetime.now(timezone.utc).isoformat()},
            prefer="return=minimal",
        )
        return {"ok": True, "duplicate": True}

    created = await _supa(
        "POST", "email_messages",
        payload={
            "mailbox_id": mailbox["mailbox_id"],
            "direction": "inbound",
            "status": "received",
            "folder": "inbox",
            "message_id": message_id,
            "from_address": from_address,
            "from_name": from_name or None,
            "subject": subject,
            "text_body": body_text,
            "html_body": body_html,
            "is_read": False,
            "is_starred": False,
            "is_important": False,
            "snippet": snippet,
            "received_at": received.get("created_at") or data.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "resend_email_id": email_id,
            "resend_event_id": webhook_id,
            "in_reply_to": received.get("in_reply_to"),
            "references_header": received.get("references"),
        },
        prefer="return=representation",
    )
    if not created:
        raise HTTPException(status_code=502, detail="Could not save the received email")
    row_id = int(created[0]["email_message_id"])
    recipient_rows = []
    for kind in ("to", "cc", "bcc"):
        addresses = received.get(kind) or data.get(kind) or []
        if isinstance(addresses, str):
            addresses = [addresses]
        for address in addresses:
            recipient = parseaddr(str(address))[1].lower().strip()
            if recipient:
                recipient_rows.append({"email_message_id": row_id, "recipient_type": kind, "email_address": recipient})
    if recipient_rows:
        await _supa("POST", "email_recipients", payload=recipient_rows, prefer="return=minimal")
    return {"ok": True, "email_message_id": row_id}
