"""Validation tests for combo-pack admin payloads."""
from __future__ import annotations

import os
import uuid

import pytest


def _combo_input_class(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:password@example.com:5432/postgres")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-" + "x" * 48)
    from ADMINS.combos.routes import ComboInput
    return ComboInput


def test_combo_input_accepts_live_sum(monkeypatch):
    ComboInput = _combo_input_class(monkeypatch)
    value = ComboInput(
        combo_code="RT-COMBO-TEST",
        name="Test Combo",
        slug="test-combo",
        pricing_mode="LIVE_SUM",
        items=[{"product_id": str(uuid.uuid4()), "quantity": 2}],
    )
    assert value.pricing_mode == "LIVE_SUM"
    assert value.items[0].quantity == 2


def test_combo_input_rejects_manual_pricing_without_price(monkeypatch):
    ComboInput = _combo_input_class(monkeypatch)
    with pytest.raises(ValueError):
        ComboInput(
            combo_code="RT-COMBO-TEST",
            name="Test Combo",
            slug="test-combo",
            pricing_mode="MANUAL",
            items=[{"product_id": str(uuid.uuid4()), "quantity": 1}],
        )


def test_combo_input_rejects_duplicate_product_lines(monkeypatch):
    ComboInput = _combo_input_class(monkeypatch)
    product_id = str(uuid.uuid4())
    with pytest.raises(ValueError, match="only appear once"):
        ComboInput(
            combo_code="RT-COMBO-TEST",
            name="Test Combo",
            slug="test-combo",
            items=[
                {"product_id": product_id, "quantity": 1},
                {"product_id": product_id, "quantity": 2},
            ],
        )


def test_combo_input_rejects_unsafe_image_url(monkeypatch):
    ComboInput = _combo_input_class(monkeypatch)
    with pytest.raises(ValueError, match="HTTPS image URL"):
        ComboInput(
            combo_code="RT-COMBO-TEST",
            name="Test Combo",
            slug="test-combo",
            image_url="javascript:alert(1)",
            items=[{"product_id": str(uuid.uuid4()), "quantity": 1}],
        )
