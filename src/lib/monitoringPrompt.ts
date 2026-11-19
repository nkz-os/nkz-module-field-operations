import { API_ORIGIN } from './apiOrigin';
import type { RecordKind } from './recordModel';

/** The state check must never hold the sowing record longer than this. */
export const STATE_TIMEOUT_MS = 5000;

export type ActivationResult = 'ok' | 'pending' | 'forbidden' | 'error';
type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

/**
 * True when the user holds one of the roles vegetation lets activate. When the roles of the
 * user or of the module are unknown the answer is true: the core's 403 is explained instead.
 */
export function canActivate(userRoles: string[], activationRoles: string[]): boolean {
  if (userRoles.length === 0 || activationRoles.length === 0) return true;
  return activationRoles.some((r) => userRoles.includes(r));
}

async function readState(parcelId: string, userRoles: string[], doFetch: FetchLike, signal: AbortSignal): Promise<{ start: string } | null> {
  const resp = await doFetch(`${API_ORIGIN}/api/vegetation/parcels/${encodeURIComponent(parcelId)}/monitoring`,
    { credentials: 'include', signal });
  if (resp.status !== 200) return null;
  const data = await resp.json();
  const start = data?.period?.start;
  if (data?.needs_activation !== true || typeof start !== 'string' || !start) return null;
  const roles = Array.isArray(data.activation_roles) ? (data.activation_roles as string[]) : [];
  return canActivate(userRoles, roles) ? { start } : null;
}

/**
 * After a recorded sowing: the start date to offer satellite monitoring from, or null to carry on
 * exactly as before (not a sowing, any non-200, any error, timeout, no need, no permission).
 */
export async function resolveMonitoringPrompt(
  kind: RecordKind, parcelId: string, userRoles: string[], doFetch: FetchLike = (u, i) => fetch(u, i),
): Promise<{ start: string } | null> {
  if (kind !== 'sowing' || !parcelId) return null;
  const ctrl = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<null>((resolve) => {
    timer = setTimeout(() => { ctrl.abort(); resolve(null); }, STATE_TIMEOUT_MS);
  });
  try {
    return await Promise.race([readState(parcelId, userRoles, doFetch, ctrl.signal).catch(() => null), timeout]);
  } finally {
    clearTimeout(timer);
  }
}

/** Ask the core to activate satellite monitoring on the parcel. */
export async function activateMonitoring(parcelId: string, doFetch: FetchLike = (u, i) => fetch(u, i)): Promise<ActivationResult> {
  try {
    const resp = await doFetch(
      `${API_ORIGIN}/api/entities/parcels/${encodeURIComponent(parcelId)}/modules/vegetation-prime/activate`,
      { method: 'POST', credentials: 'include' });
    if (resp.status === 201) return 'ok';
    if (resp.status === 502) return 'pending';
    if (resp.status === 403) return 'forbidden';
    return 'error';
  } catch {
    return 'error';
  }
}
