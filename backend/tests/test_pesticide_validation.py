"""Tests for spraying pesticide validation (P1)."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.pesticide_validation import (
    PesticideValidationResult,
    enforce_spraying_validation,
    validate_spraying_product,
)

client = TestClient(app)


class TestValidateSprayingProduct:
    def test_authorized_product(self):
        with patch(
            "app.services.pesticide_validation.resolve_parcel_crop_eppo",
            return_value="TRZAX",
        ), patch(
            "app.services.pesticide_validation.fetch_authorized_substances",
            return_value=([{"name": "Amistar"}], None),
        ):
            result = validate_spraying_product("t1", "parcel:1", "Amistar")
            assert result.status == "authorized"

    def test_unauthorized_product(self):
        with patch(
            "app.services.pesticide_validation.resolve_parcel_crop_eppo",
            return_value="TRZAX",
        ), patch(
            "app.services.pesticide_validation.fetch_authorized_substances",
            return_value=([{"name": "Amistar"}], None),
        ):
            result = validate_spraying_product("t1", "parcel:1", "Glyphosate")
            assert result.status == "not_authorized"

    def test_missing_crop_skips(self):
        with patch(
            "app.services.pesticide_validation.resolve_parcel_crop_eppo",
            return_value=None,
        ):
            result = validate_spraying_product("t1", "parcel:1", "Amistar")
            assert result.status == "skipped"

    def test_catalog_unavailable_fail_open(self):
        with patch(
            "app.services.pesticide_validation.resolve_parcel_crop_eppo",
            return_value="TRZAX",
        ), patch(
            "app.services.pesticide_validation.fetch_authorized_substances",
            return_value=([], "timeout"),
        ):
            result = validate_spraying_product("t1", "parcel:1", "Amistar")
            assert result.status == "unknown_substance"


class TestEnforceSprayingValidation:
    def test_non_spraying_skipped(self):
        assert enforce_spraying_validation("t1", "p1", "sowing", {}) is None

    def test_raises_on_reject(self):
        with patch(
            "app.services.pesticide_validation.validate_spraying_product",
            return_value=PesticideValidationResult(
                status="not_authorized",
                detail="rejected",
                crop_eppo="TRZAX",
                product_name="Bad",
            ),
        ):
            with pytest.raises(ValueError, match="rejected"):
                enforce_spraying_validation(
                    "t1", "p1", "spraying", {"productName": "Bad"},
                )


class TestOperationsApiPesticide:
    def test_create_spraying_rejected_returns_422(self):
        with patch(
            "app.api.operations.enforce_spraying_validation",
            side_effect=ValueError("not authorized for crop"),
        ):
            resp = client.post(
                "/api/field-operations/operations",
                json={
                    "parcel_id": "urn:ngsi-ld:AgriParcel:t:p1",
                    "operation_type": "spraying",
                    "work_order": "WO-1",
                    "operator": "op@test.com",
                    "productName": "Glyphosate",
                },
                headers={"X-Tenant-ID": "test-tenant"},
            )
            assert resp.status_code == 422
            data = resp.json()["detail"]
            assert data["code"] == "pesticide_not_authorized"

    def test_create_spraying_authorized(self):
        with patch("app.api.operations.enforce_spraying_validation") as mock_val, \
             patch("app.api.operations.create_operation") as mock_create:
            mock_val.return_value = PesticideValidationResult(
                status="authorized", detail="ok",
            )
            mock_create.return_value = {"id": "urn:ngsi-ld:AgriParcelOperation:t:abc"}

            resp = client.post(
                "/api/field-operations/operations",
                json={
                    "parcel_id": "urn:ngsi-ld:AgriParcel:t:p1",
                    "operation_type": "spraying",
                    "work_order": "WO-1",
                    "operator": "op@test.com",
                    "productName": "Amistar",
                },
                headers={"X-Tenant-ID": "test-tenant"},
            )
            assert resp.status_code == 200
            mock_create.assert_called_once()

    def test_validate_pesticide_endpoint(self):
        with patch(
            "app.api.operations.validate_spraying_product",
            return_value=PesticideValidationResult(
                status="authorized",
                detail="ok",
                crop_eppo="TRZAX",
                product_name="Amistar",
            ),
        ):
            resp = client.get(
                "/api/field-operations/validate-pesticide",
                params={"parcel_id": "p1", "product_name": "Amistar"},
                headers={"X-Tenant-ID": "test-tenant"},
            )
            assert resp.status_code == 200
            assert resp.json()["authorized"] is True


# ── Task 7: new flow (crop-name resolve + CUE ROPO) ──────────────────────────

import app.services.pesticide_validation as pv  # noqa: E402


def _row(name, ingr=""):
    return {"nombre_comercial": name, "ingrediente_activo": ingr}


def test_authorized_product_cue(monkeypatch):
    monkeypatch.setattr(pv, "resolve_parcel_crop_eppo", lambda t, p: "TRZAX")
    monkeypatch.setattr(pv, "_resolve_crop_name_es", lambda e, t, u="": "trigo")
    with patch.object(pv, "get_ropo_products", return_value=[_row("Roundup")]):
        res = pv.validate_spraying_product("montiko", "urn:p", "Roundup")
    assert res.status == "authorized"


def test_not_authorized_product_cue(monkeypatch):
    monkeypatch.setattr(pv, "resolve_parcel_crop_eppo", lambda t, p: "TRZAX")
    monkeypatch.setattr(pv, "_resolve_crop_name_es", lambda e, t, u="": "trigo")
    with patch.object(pv, "get_ropo_products", return_value=[_row("OtraCosa")]):
        res = pv.validate_spraying_product("montiko", "urn:p", "Roundup")
    assert res.status == "not_authorized"


def test_crop_name_unresolved_failopen(monkeypatch):
    monkeypatch.setattr(pv, "resolve_parcel_crop_eppo", lambda t, p: "TRZAX")
    monkeypatch.setattr(pv, "_resolve_crop_name_es", lambda e, t, u="": None)
    res = pv.validate_spraying_product("montiko", "urn:p", "Roundup")
    assert res.status == "unknown_substance"


def test_cue_down_failopen(monkeypatch):
    import httpx  # noqa: PLC0415

    monkeypatch.setattr(pv, "resolve_parcel_crop_eppo", lambda t, p: "TRZAX")
    monkeypatch.setattr(pv, "_resolve_crop_name_es", lambda e, t, u="": "trigo")

    def _boom(*a, **k):
        raise httpx.HTTPError("down")

    with patch.object(pv, "get_ropo_products", side_effect=_boom):
        res = pv.validate_spraying_product("montiko", "urn:p", "Roundup")
    assert res.status == "unknown_substance"
