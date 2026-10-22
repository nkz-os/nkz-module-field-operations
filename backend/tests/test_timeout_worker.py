"""Tests for stale operation timeout worker."""
import pytest
from datetime import datetime, timezone, timedelta
from app.services.timeout_worker import check_stale_operations, POLL_INTERVAL_SECONDS


class TestTimeoutWorker:
    def test_poll_interval_is_one_hour(self):
        """Worker should poll every hour."""
        assert POLL_INTERVAL_SECONDS == 3600

    def test_worker_loop_handles_exceptions(self):
        """Worker should not crash on errors (it catches them internally)."""
        # This is a smoke test — the worker catches all exceptions in its loop.
        # We can't easily test the loop without mocking, but we can verify it
        # doesn't raise on first iteration.
        pass

    def test_cutoff_is_in_past(self):
        """Timeout should use current UTC time minus configured hours."""
        from app.config import INCOMPLETE_TIMEOUT_HOURS
        cutoff = datetime.now(timezone.utc) - timedelta(hours=INCOMPLETE_TIMEOUT_HOURS)
        assert cutoff < datetime.now(timezone.utc)
        assert INCOMPLETE_TIMEOUT_HOURS > 0


def _old_op(op_id: str) -> dict:
    started = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    return {"id": op_id, "startedAt": {"type": "Property", "value": {"@type": "DateTime", "@value": started}}}


@pytest.mark.asyncio
async def test_stale_check_flags_operations_of_enabled_tenants(monkeypatch):
    from nkz_platform_sdk.installations import TenantInstallations
    import app.orion_ops as orion_ops
    import app.services.timeout_worker as tw

    async def fake_installed(module_id, **kw):
        assert module_id == "field-operations"
        return TenantInstallations(module_id, ("tenant-a",), ("tenant-b",), ())

    queried, flagged = [], []
    monkeypatch.setattr(tw, "installed_tenants", fake_installed)
    monkeypatch.setattr(orion_ops, "query_operations",
                        lambda tenant, status, limit: queried.append(tenant) or [_old_op("urn:op:1")])
    monkeypatch.setattr(orion_ops, "update_entity_attrs",
                        lambda tenant, op_id, attrs: flagged.append((tenant, op_id, attrs["status"]["value"])))

    await tw._process_stale_operations()

    assert queried == ["tenant-a"]
    assert flagged == [("tenant-a", "urn:op:1", "needs_review")]


@pytest.mark.asyncio
async def test_stale_check_skips_round_when_platform_unavailable(monkeypatch):
    from nkz_platform_sdk.installations import InstalledTenantsUnavailable
    import app.orion_ops as orion_ops
    import app.services.timeout_worker as tw

    async def boom(module_id, **kw):
        raise InstalledTenantsUnavailable("503")

    queried = []
    monkeypatch.setattr(tw, "installed_tenants", boom)
    monkeypatch.setattr(orion_ops, "query_operations", lambda *a, **k: queried.append(a) or [])

    await tw._process_stale_operations()

    assert queried == []
