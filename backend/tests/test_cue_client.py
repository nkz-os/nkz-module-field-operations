from unittest.mock import patch, MagicMock
import app.services.cue_client as cc


def test_get_ropo_products_builds_request():
    resp = MagicMock()
    resp.json.return_value = [{"nombre_comercial": "Prod A"}]
    resp.raise_for_status.return_value = None
    client = MagicMock()
    client.get.return_value = resp
    client.__enter__ = lambda s: client
    client.__exit__ = lambda *a: False
    with patch("httpx.Client", return_value=client):
        out = cc.get_ropo_products("trigo", "montiko")
    assert out == [{"nombre_comercial": "Prod A"}]
    args, kwargs = client.get.call_args
    # URL must include the CUE blueprint prefix
    assert "/api/modules/cue/productos-ropo" in (args[0] if args else kwargs.get("url", ""))
    assert kwargs["params"] == {"cultivo": "trigo", "estado": "autorizado"}
    assert "X-Internal-Service-Secret" in kwargs["headers"]
    assert kwargs["headers"]["X-Tenant-ID"] == "montiko"
