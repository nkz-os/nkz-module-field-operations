"""Platform roles (Keycloak realm roles) map onto field-operations actors."""
from app.api.operations import _resolve_actor


def test_tenant_admin_platform_roles():
    assert _resolve_actor(["Farmer", "TenantAdmin"]) == "tenant_admin"
    assert _resolve_actor(["PlatformAdmin"]) == "tenant_admin"


def test_technical_consultant_is_field_manager():
    assert _resolve_actor(["TechnicalConsultant"]) == "field_manager"


def test_farmer_is_user():
    assert _resolve_actor(["Farmer"]) == "user"
    assert _resolve_actor([]) == "user"


def test_legacy_names_still_work():
    assert _resolve_actor(["tenant_admin"]) == "tenant_admin"
    assert _resolve_actor(["field_manager"]) == "field_manager"
