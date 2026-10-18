(() => {
  // Browser zoom and pinch-zoom are per-visitor UI preferences. Keep them
  // available and never persist viewport scale or section dimensions.
  const viewportMeta = document.querySelector('meta[name="viewport"]');
  if (viewportMeta) {
    viewportMeta.setAttribute('content', 'width=device-width, initial-scale=1.0, viewport-fit=cover');
  } else {
    const meta = document.createElement('meta');
    meta.name = 'viewport';
    meta.content = 'width=device-width, initial-scale=1.0, viewport-fit=cover';
    document.head.appendChild(meta);
  }

  const cfg = window.RTC_MAIL_CONFIG || {};
  const api = window.RTCMailAPI;
  const page = location.pathname.toLowerCase();

  const routes = {
    inbox: "/FRONTEND/EMAIL/PAGES/inbox.html",
    login: "/FRONTEND/EMAIL/PAGES/login.html",
    sent: "/FRONTEND/EMAIL/PAGES/sent.html",
    drafts: "/FRONTEND/EMAIL/PAGES/drafts.html",
    starred: "/FRONTEND/EMAIL/PAGES/starred.html",
    archived: "/FRONTEND/EMAIL/PAGES/archived.html",
    trash: "/FRONTEND/EMAIL/PAGES/trash.html",
    search: "/FRONTEND/EMAIL/PAGES/search.html",
    compose: "/FRONTEND/EMAIL/PAGES/compose.html",
    message: "/FRONTEND/EMAIL/PAGES/message.html",
    mailboxes: "/FRONTEND/EMAIL/PAGES/mailboxes.html",
    settings: "/FRONTEND/EMAIL/PAGES/settings.html"
  };

  function notify(text, error=false) {
    document.querySelectorAll(".rtc-mail-api-error").forEach(x => x.remove());
    const el = document.createElement("div");
    el.className = error ? "rtc-mail-api-error" : "rtc-mail-live-badge";
    el.textContent = text;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), error ? 6000 : 2400);
  }

  async function hydrateMailTheme() {
    try {
      const themePage = /login/i.test(page) ? 'login' : 'inbox';
      const response = await fetch('/api/v1/cms/theme/mail/' + themePage, {credentials:'omit', headers:{Accept:'application/json'}});
      if (!response.ok) return;
      const data = await response.json();
      const theme = data && data.page;
      if (!theme) return;
      const root = document.documentElement;
      const vars = {
        '--rtc-mail-bg': theme.background_color,
        '--rtc-mail-surface': theme.surface_color,
        '--rtc-mail-section': theme.section_color,
        '--rtc-mail-header': theme.header_color,
        '--rtc-mail-footer': theme.footer_color,
        '--rtc-mail-text': theme.text_color,
        '--rtc-mail-muted': theme.muted_text_color,
        '--rtc-mail-heading': theme.heading_color,
        '--rtc-mail-primary': theme.primary_color,
        '--rtc-mail-primary-dark': theme.primary_dark_color,
        '--rtc-mail-secondary': theme.secondary_color,
        '--rtc-mail-accent': theme.accent_color,
        '--rtc-mail-border': theme.border_color,
        '--rtc-mail-font-heading': theme.font_heading,
        '--rtc-mail-font-body': theme.font_body,
        '--rtc-mail-radius': theme.radius_medium
      };
      Object.entries(vars).forEach(([key, value]) => {
        if (typeof value === 'string' && value.length < 160 && !/[{};]/.test(value)) root.style.setProperty(key, value);
      });
      root.dataset.dbMailTheme = themePage;
      for (const component of Array.isArray(data.components) ? data.components : []) {
        const key = String(component.component_key || '');
        if (!/^[a-z0-9_-]{1,100}$/i.test(key)) continue;
        document.querySelectorAll('[data-theme-component="' + key + '"]').forEach(el => {
          if (component.content_value) el.textContent = String(component.content_value);
          if (component.text_color) el.style.color = String(component.text_color);
          if (component.background_color) el.style.backgroundColor = String(component.background_color);
          if (component.border_color) el.style.borderColor = String(component.border_color);
          if (component.padding) el.style.padding = String(component.padding);
          if (component.border_radius) el.style.borderRadius = String(component.border_radius);
        });
      }
    } catch (error) {
      console.warn('Database mail theme unavailable', error);
    }
  }

  function localizeAssets() {
    document.querySelectorAll("img[src*='googleusercontent.com/aida']").forEach(img => {
      img.src = cfg.logo || "/ASSETS/LOGO.jpeg";
    });
    document.querySelectorAll("img[src*='googleusercontent.com/aida-public']").forEach(img => {
      img.src = cfg.logo || "/ASSETS/LOGO.jpeg";
    });
  }

  function wirePaths() {
    document.querySelectorAll("[data-path]").forEach(el => {
      const p = (el.getAttribute("data-path") || "").toLowerCase();
      let key = null;
      if (p.includes("inbox")) key = "inbox";
      else if (p.includes("sent") || p.includes("outbox")) key = "sent";
      else if (p.includes("draft")) key = "drafts";
      else if (p.includes("starred")) key = "starred";
      else if (p.includes("archived")) key = "archived";
      else if (p.includes("trash")) key = "trash";
      else if (p.includes("search")) key = "search";
      else if (p.includes("compose")) key = "compose";
      else if (p.includes("mailbox")) key = "mailboxes";
      else if (p.includes("settings")) key = "settings";
      if (key && routes[key]) {
        el.setAttribute("href", routes[key]);
      }
    });
  }

  function getMailboxId() {
    return Number(localStorage.getItem("rtc-mailbox-id") || cfg.defaultMailboxId || 0) || null;
  }

  async function ensureMailbox() {
    if (!api) return null;
    let id = getMailboxId();
    if (id) return id;
    const boxes = await api.mailboxes();
    if (boxes && boxes.length) {
      id = Number(boxes[0].id);
      localStorage.setItem("rtc-mailbox-id", String(id));
      return id;
    }
    return null;
  }

  function displayValue(value) {
    return value == null ? "" : String(value);
  }

  function makeRow(item) {
    const sender = displayValue(item.to_address || item.from_address || "Unknown");
    const initials = sender.replace(/<.*?>/g, "").trim().split(/[\s@._-]+/).filter(Boolean).slice(0,2).map(x => x[0]).join("").toUpperCase() || "?";
    const row = document.createElement("div");
    row.className = `email-row group relative flex items-start gap-space-sm px-space-md py-space-sm ${item.is_read ? "bg-white" : "bg-orange-50/50 border-l-4 border-l-tag-notifications"} hover:bg-orange-50/70 transition-colors cursor-pointer`;
    row.dataset.emailId = item.id;
    row.innerHTML = `
      <div class="pt-0.5 flex flex-col items-center gap-2 select-none">
        <button class="star-btn ${item.is_starred ? "text-amber-500" : "text-secondary"} hover:scale-110 transition-transform" type="button">
          <span class="material-symbols-outlined text-[20px]" style="font-variation-settings:'FILL' ${item.is_starred ? 1 : 0};">star</span>
        </button>
      </div>
      <div class="flex-1 min-w-0">
        <div class="flex items-center justify-between gap-space-xs mb-0.5">
          <div class="flex items-center gap-space-xs min-w-0">
            <span class="w-6 h-6 rounded-full bg-tag-support text-on-primary flex items-center justify-center font-label-sm text-label-sm font-bold flex-shrink-0">${initials}</span>
            <span class="font-title-sm text-title-sm ${item.is_read ? "font-medium" : "font-bold"} text-on-surface truncate">${escapeHtml(sender)}</span>
          </div>
          <span class="font-label-sm text-label-sm text-secondary">${formatDate(item.created_at)}</span>
        </div>
        <div class="font-title-sm text-title-sm ${item.is_read ? "font-medium" : "font-bold"} text-on-surface truncate mb-0.5">${escapeHtml(item.subject || "(No subject)")}</div>
        <p class="font-body-sm text-body-sm text-secondary line-clamp-2">${escapeHtml(item.to_address || "")}</p>
      </div>
    `;
    row.querySelector(".star-btn").addEventListener("click", async e => {
      e.stopPropagation();
      try { await api.star(item.id, !item.is_starred); notify(item.is_starred ? "Star removed" : "Conversation starred"); }
      catch (err) { notify(err.message, true); }
    });
    row.addEventListener("click", async () => {
      try { await api.read(item.id, true); localStorage.setItem("rtc-mail-open-message", String(item.id)); location.href = routes.message; }
      catch (err) { notify(err.message, true); }
    });
    return row;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" }[c]));
  }

  function formatDate(v) {
    if (!v) return "";
    const d = new Date(v);
    if (Number.isNaN(d.getTime())) return String(v);
    return d.toLocaleString("en-IN", { day:"2-digit", month:"short", hour:"2-digit", minute:"2-digit" });
  }

  async function hydrateInbox() {
    if (!/inbox/i.test(page) && page !== "/") return;
    const id = await ensureMailbox();
    if (!id) { notify("No active mailbox is configured.", true); return; }
    const items = await api.inbox(id);
    const existing = [...document.querySelectorAll(".email-row")];
    if (!existing.length) return;
    const parent = existing[0].parentElement;
    existing.forEach(x => x.remove());
    items.forEach(item => parent.appendChild(makeRow(item)));
  }


  async function hydrateLiveFolder() {
    const id = await ensureMailbox();
    if (!id) return;
    let kind = null;
    if (/\/inbox\.html$/i.test(page) || page === "/") kind = "inbox";
    else if (/\/sent\.html$/i.test(page)) kind = "sent";
    else if (/\/starred\.html$/i.test(page)) kind = "starred";
    else if (/\/archived\.html$/i.test(page)) kind = "archived";
    else if (/\/trash\.html$/i.test(page)) kind = "trash";
    else if (/\/drafts\.html$/i.test(page)) kind = "drafts";
    else if (/\/search\.html$/i.test(page)) kind = "search";
    if (!kind) return;

    const load = async () => {
      const queryInput = document.getElementById("globalSearchInput")
        || document.getElementById("omnisearch-input")
        || document.getElementById("input-search")
        || document.querySelector('input[type="search"],input[placeholder*="Search" i]');
      const q = (queryInput?.value || "").trim();
      if (kind === "search" && !q) return;
      const method = kind === "search" ? "search" : kind;
      const items = await api[method](id, ...(kind === "search" ? [q] : []));
      const selectors = {
        inbox: "#email-list-container",
        sent: "#sent-list-container",
        starred: "#feed-live-container",
        archived: "#email-list-wrapper",
        trash: "#view-state-list",
        drafts: "#draftsFeedContainer, #draftsList",
        search: "#stateResults"
      };
      const host = document.querySelector(selectors[kind]) || document.querySelector("[data-mail-list]");
      const previousRows = [...document.querySelectorAll(".email-row")];
      const target = host || previousRows[0]?.parentElement;
      if (!target) return;
      if (previousRows.length) previousRows.forEach(row => row.remove());
      if (kind === "search" || kind === "drafts" || kind === "trash") {
        target.querySelectorAll(".rtc-mail-empty").forEach(node => node.remove());
      }
      if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "rtc-mail-empty p-6 text-center text-sm text-secondary";
        empty.textContent = kind === "inbox" ? "No messages in this inbox." : kind === "sent" ? "No sent messages yet." : kind === "starred" ? "No starred messages." : kind === "archived" ? "No archived messages." : kind === "trash" ? "Trash is empty." : kind === "drafts" ? "No saved drafts." : "No matching messages.";
        target.appendChild(empty);
        return;
      }
      target.querySelectorAll(".rtc-mail-empty").forEach(node => node.remove());
      items.forEach(item => target.appendChild(makeRow(item)));
    };

    try { await load(); }
    catch (err) { notify(err.message || "Could not load messages", true); }

    const searchInput = document.getElementById("globalSearchInput")
      || document.getElementById("omnisearch-input")
      || document.getElementById("input-search");
    if (kind === "search" && searchInput && !searchInput.dataset.rtcLiveSearch) {
      searchInput.dataset.rtcLiveSearch = "1";
      let timer;
      searchInput.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(() => load().catch(err => notify(err.message, true)), 250);
      });
    }
  }

  async function hydrateMessage() {
    if (!/message/i.test(page)) return;
    const id = Number(localStorage.getItem("rtc-mail-open-message") || 0);
    if (!id) return;
    const data = await api.message(id);
    const title = document.querySelector("h1, h2");
    if (title && data.subject) title.textContent = data.subject;
    const bodyTargets = document.querySelectorAll("[data-email-body], .email-body, article");
    const host = bodyTargets.length ? bodyTargets[bodyTargets.length - 1] : null;
    if (host && (data.body_html || data.body_text)) {
      host.replaceChildren();
      if (data.body_html) {
        // HTML email bodies are untrusted. Isolate them in a sandboxed iframe;
        // never inject remote mail HTML into the privileged mail application's DOM.
        const frame = document.createElement("iframe");
        frame.title = "Email message body";
        frame.setAttribute("sandbox", "");
        frame.setAttribute("referrerpolicy", "no-referrer");
        frame.style.cssText = "display:block;width:100%;min-height:320px;border:0;background:white";
        frame.srcdoc = "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><style>body{font:14px/1.55 system-ui,sans-serif;overflow-wrap:anywhere}img,table,video{max-width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body>" + String(data.body_html) + "</body></html>";
        host.appendChild(frame);
      } else {
        const pre = document.createElement("pre");
        pre.style.cssText = "white-space:pre-wrap;overflow-wrap:anywhere";
        pre.textContent = data.body_text || "";
        host.appendChild(pre);
      }
    }
  }

  async function hydrateCompose() {
    if (!/compose/i.test(page)) return;
    const id = await ensureMailbox();
    if (!id) return;
    const form = document.querySelector("form");
    if (!form || form.dataset.rtcBound) return;
    form.dataset.rtcBound = "1";
    form.addEventListener("submit", async e => {
      e.preventDefault();
      const inputs = [...form.querySelectorAll("input, textarea")];
      const byName = n => form.querySelector(`[name="${n}"]`) || inputs.find(x => (x.placeholder || "").toLowerCase().includes(n));
      const to = (byName("to")?.value || "").split(",").map(x => x.trim()).filter(Boolean);
      const subject = byName("subject")?.value || "";
      const body = form.querySelector("textarea")?.value || "";
      try {
        await api.send({ mailbox_id:id, to, cc:[], bcc:[], subject, body_text:body, body_html:null });
        notify("Email sent successfully.");
      } catch (err) { notify(err.message, true); }
    });
  }

  async function boot() {
    localizeAssets();
    hydrateMailTheme();
    wirePaths();
    try {
      await ensureMailbox();
      await hydrateLiveFolder();
      await hydrateMessage();
      await hydrateCompose();
      if (/inbox/i.test(page)) notify("RTC Crackers Mail connected");
    } catch (err) {
      if (err && err.status === 401 && !/\/login\.html$/i.test(page)) { location.replace(routes.login); return; }
      notify(err.message || "Mail service unavailable", true);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
