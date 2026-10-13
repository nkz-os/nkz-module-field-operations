"""Crop-cycle runtime: Orion notifications in, crop-cycle facts out.

Inert unless ``CROP_CYCLES_WRITER_ENABLED``: no subscriptions, no worker, no
sweep, and notifications are acknowledged and dropped.

- Notified parcels wait in a deduplicated queue and are reconciled off the
  request: without throttling a burst of edits arrives as many notifications,
  and answering each inline would make Orion time out and pause the subscription.
- A daily sweep reconciles every parcel of the tenants where the module is
  enabled, catching what notifications missed.
- Subscriptions follow where the platform says the module is installed (SDK
  ``reconcile_installations``), at start-up, hourly and on the install hint.
"""

from __future__ import annotations

import asyncio
import logging

from nkz_platform_sdk.installations import InstalledTenantsUnavailable, installed_tenants
from nkz_platform_sdk.notify_auth import derived_tokens_from_env
from nkz_platform_sdk.orion import OrionClient
from nkz_platform_sdk.subscriptions import SubscriptionRegistrar

from .. import config
from .crop_cycles_writer import list_parcels, reconcile_parcel

logger = logging.getLogger(__name__)

MODULE_ID = "field-operations"
SWEEP_INTERVAL_S = 24 * 3600
SUBSCRIPTION_HEAL_MINUTES = 60

_pending: set[tuple[str, str]] = set()
_wake: asyncio.Event | None = None
_registrar: SubscriptionRegistrar | None = None


def _event() -> asyncio.Event:
    global _wake
    if _wake is None:
        _wake = asyncio.Event()
    return _wake


def _client(tenant_id: str) -> OrionClient:
    return OrionClient(tenant_id, base_url=config.ORION_URL, context_url=config.CONTEXT_URL)


def enqueue(tenant_id: str | None, parcels: set[str]) -> None:
    """Queue notified parcels. A no-op while the writer is disabled."""
    if not config.CROP_CYCLES_WRITER_ENABLED or not tenant_id or not parcels:
        return
    _pending.update((tenant_id, p) for p in parcels)
    _event().set()


async def drain() -> None:
    """Reconcile every queued (tenant, parcel) once; one failing parcel never drops the batch."""
    while _pending:
        batch = sorted(_pending)
        _pending.clear()
        for tenant_id, parcel in batch:
            client = _client(tenant_id)
            try:
                await reconcile_parcel(client, tenant_id, parcel)
            except Exception as e:  # noqa: BLE001
                logger.warning("crop-cycle reconcile failed tenant=%s parcel=%s: %s", tenant_id, parcel, e)
            finally:
                await client.close()


async def worker() -> None:
    wake = _event()
    while True:
        await wake.wait()
        wake.clear()
        await drain()


async def sweep_once() -> dict:
    """Reconcile every parcel of the tenants where the module is enabled."""
    stats = {"tenants": 0, "parcels": 0, "written": 0, "errors": 0}
    try:
        installs = await installed_tenants(MODULE_ID)
    except InstalledTenantsUnavailable as e:
        logger.warning("crop-cycle sweep skipped: %s", e)
        return {**stats, "skipped": "unavailable"}
    for tenant_id in installs.enabled:
        stats["tenants"] += 1
        client = _client(tenant_id)
        try:
            parcels = await list_parcels(client)
            for parcel in parcels:
                stats["parcels"] += 1
                try:
                    stats["written"] += len(await reconcile_parcel(client, tenant_id, parcel))
                except Exception as e:  # noqa: BLE001
                    stats["errors"] += 1
                    logger.warning("crop-cycle sweep failed tenant=%s parcel=%s: %s", tenant_id, parcel, e)
        except Exception as e:  # noqa: BLE001
            stats["errors"] += 1
            logger.warning("crop-cycle sweep: parcels unreadable tenant=%s: %s", tenant_id, e)
        finally:
            await client.close()
    logger.info("crop-cycle sweep: %s", stats)
    return stats


async def sweep_loop() -> None:
    while True:
        try:
            await sweep_once()
        except Exception as e:  # noqa: BLE001
            logger.warning("crop-cycle sweep failed: %s", e)
        await asyncio.sleep(SWEEP_INTERVAL_S)


def get_registrar() -> SubscriptionRegistrar | None:
    """One registrar per process (its lock serializes heal and hints); None without the secret."""
    global _registrar
    if _registrar is None:
        secret = config.INTERNAL_SERVICE_SECRET
        if not secret:
            logger.error("INTERNAL_SERVICE_SECRET not set — crop-cycle subscriptions NOT registered")
            return None
        _registrar = SubscriptionRegistrar(
            orion_url=config.ORION_URL,
            notification_url=config.CROP_CYCLES_NOTIFY_URL,
            # No throttling: Orion drops notifications inside the window, so a
            # burst of edits would only be seen by the sweep. Orion rejects 0.
            subscriptions=[
                {"type": "AgriCrop", "throttling": None},
                {"type": "AgriParcelOperation", "throttling": None},
            ],
            module_name=MODULE_ID,
            context_url=config.CONTEXT_URL,
            internal_secret=secret,
            derived_tokens=derived_tokens_from_env(),
        )
    return _registrar


async def reconcile_subscriptions() -> dict | None:
    """Converge the crop-cycle subscriptions on where the module is installed."""
    if not config.CROP_CYCLES_WRITER_ENABLED:
        return None
    registrar = get_registrar()
    if registrar is None:
        return None
    result = await registrar.reconcile_installations(MODULE_ID)
    logger.info("crop-cycle subscriptions: %s", result)
    return result


async def _subscriptions_loop() -> None:
    try:
        await reconcile_subscriptions()
    except Exception as e:  # noqa: BLE001
        logger.warning("crop-cycle subscriptions: initial reconcile failed: %s", e)
    registrar = get_registrar()
    if registrar is not None:
        await registrar.periodic_reconcile(MODULE_ID, SUBSCRIPTION_HEAL_MINUTES)


def start() -> list[asyncio.Task]:
    """Background tasks for the writer, or none while it is disabled."""
    if not config.CROP_CYCLES_WRITER_ENABLED:
        logger.info("crop-cycle writer disabled (CROP_CYCLES_WRITER_ENABLED)")
        return []
    return [
        asyncio.create_task(worker()),
        asyncio.create_task(_subscriptions_loop()),
        asyncio.create_task(sweep_loop()),
    ]
