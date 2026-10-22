"""Bridge to nkz-module-cue for SIEX product validation and registration."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
import httpx

from ..config import CUE_API_URL, INTERNAL_SERVICE_SECRET

router = APIRouter(prefix="/api/field-operations/cue", tags=["cue-bridge"])

# CUE routes live under the module blueprint prefix; internal reads/SIEX writes
# authenticate with the internal-service secret (no user JWT to forward here).
_CUE = f"{CUE_API_URL.rstrip('/')}/api/modules/cue"


def _cue_headers(tenant_id: str) -> dict:
    return {"X-Tenant-ID": tenant_id, "X-Internal-Service-Secret": INTERNAL_SERVICE_SECRET}


def _get_tenant(request: Request) -> str:
    return request.headers.get("X-Tenant-ID", request.headers.get("NGSILD-Tenant", ""))


def _get_roles(request: Request) -> list:
    raw = request.headers.get("X-User-Roles", "")
    return [r.strip() for r in raw.split(",") if r.strip()]


@router.get("/productos-autorizados")
async def list_authorized_products(
    request: Request,
    cultivo: str = Query(None),
    tipo: str = Query("fitosanitario"),
):
    tenant_id = _get_tenant(request)
    endpoint = f"{_CUE}/productos-ropo" if tipo == "fitosanitario" else f"{_CUE}/productos-fertilizantes"
    params = {}
    if cultivo:
        params["cultivo"] = cultivo

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(endpoint, params=params, headers=_cue_headers(tenant_id))
        if resp.status_code != 200:
            raise HTTPException(502, f"CUE service returned {resp.status_code}")
        return resp.json()


@router.get("/productos-autorizados/{registry_ref}")
async def get_product_detail(
    registry_ref: str,
    request: Request,
    tipo: str = Query("fitosanitario"),
):
    tenant_id = _get_tenant(request)
    base = "productos-ropo" if tipo == "fitosanitario" else "productos-fertilizantes"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_CUE}/{base}/{registry_ref}",
            headers=_cue_headers(tenant_id),
        )
        if resp.status_code == 404:
            raise HTTPException(404, f"Product not found: {registry_ref}")
        if resp.status_code != 200:
            raise HTTPException(502, f"CUE service returned {resp.status_code}")
        return resp.json()


@router.post("/operations/{operation_id}/registrar-siex")
async def register_in_siex(operation_id: str, request: Request):
    """Manual trigger to register a completed operation in CUE/SIEX. Phase 1 only."""
    tenant_id = _get_tenant(request)
    roles = _get_roles(request)
    if "field_manager" not in roles and "tenant_admin" not in roles:
        raise HTTPException(403, "Only field_manager or tenant_admin can register in SIEX")

    from ..orion_ops import get_entity, update_entity_attrs
    entity = get_entity(tenant_id, operation_id)
    if not entity:
        raise HTTPException(404, f"Operation not found: {operation_id}")

    op_type = entity.get("operationType", {}).get("value", "")
    if op_type not in ("spraying", "fertilization"):
        raise HTTPException(400, f"SIEX registration only for spraying/fertilization, not {op_type}")

    payload = _build_siex_payload(entity)
    endpoint = f"{_CUE}/tratamientos" if op_type == "spraying" else f"{_CUE}/fertilizaciones"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(endpoint, json=payload, headers=_cue_headers(tenant_id))
        if resp.status_code not in (200, 201):
            raise HTTPException(502, f"CUE registration failed: {resp.text}")
        siex_response = resp.json()
        siex_id = siex_response.get("id", "")

        if siex_id:
            update_entity_attrs(tenant_id, operation_id, {
                "siexRecordRef": {"type": "Relationship", "object": siex_id}
            })

    return {"siex_id": siex_id, "operation_id": operation_id}


def _build_siex_payload(entity: dict) -> dict:
    def val(field, default=None):
        attr = entity.get(field)
        return attr.get("value", default) if isinstance(attr, dict) else default

    op_type = entity.get("operationType", {}).get("value", "")
    started = entity.get("startedAt", {}).get("value", {})
    fecha = started.get("@value", "") if isinstance(started, dict) else ""

    if op_type == "spraying":
        return {
            "producto_ropo": val("productRegistryRef", ""),
            "dosis": val("productRate", 0),
            "unidad_dosis": "kg/ha",
            "fecha_aplicacion": fecha,
            "metodo_aplicacion": val("applicationMethod", "foliar"),
            "velocidad_viento": val("windSpeedAtApplication"),
            "observaciones": f"Auto-generado desde AgriParcelOperation {entity.get('id','')}",
        }
    elif op_type == "fertilization":
        return {
            "producto_fertilizante": val("fertilizerRegistryRef", ""),
            "dosis_kg_ha": val("fertilizerRate", 0),
            "tipo_fertilizante": val("fertilizerType", ""),
            "composicion": val("fertilizerComposition", ""),
            "organico": val("organicFertilizer", False),
            "fecha_aplicacion": fecha,
        }
    return {}
