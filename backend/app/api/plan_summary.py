"""The signed nutrient plan of a parcel and campaign, for the notebook (art. 5.1.a). Unlike the
older notebook routes, this one verifies the gateway's signature (SDK require_auth)."""
from fastapi import APIRouter, Query
from nkz_platform_sdk.auth import AuthContext, require_auth

from ..services import fast_client

router = APIRouter(prefix="/api/field-operations", tags=["fertilization-plan"])
READ_ROLES = ["Farmer", "TechnicalConsultant", "TenantAdmin"]
PARCEL = r"^urn:ngsi-ld:AgriParcel:[A-Za-z0-9._:-]+$"


@router.get("/plan-summary")
async def get_plan_summary(parcel_id: str = Query(pattern=PARCEL, max_length=200),
                           campaign: int = Query(ge=2000, le=2100),
                           auth: AuthContext = require_auth(READ_ROLES)) -> dict:
    return await fast_client.plan_summary(auth.tenant_id, parcel_id, campaign)
