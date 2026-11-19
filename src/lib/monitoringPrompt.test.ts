import { afterEach, describe, expect, it, vi } from 'vitest';
import { activateMonitoring, canActivate, resolveMonitoringPrompt } from './monitoringPrompt';

const PARCEL = 'urn:ngsi-ld:AgriParcel:parcel-a';
const json = (status: number, body: unknown = {}) => ({ status, ok: status >= 200 && status < 300, json: async () => body }) as Response;
const state = (over: Record<string, unknown> = {}) => json(200, {
  needs_activation: true, period: { start: '2026-11-18' }, activation_roles: ['Farmer', 'TenantAdmin'], ...over,
});

afterEach(() => { vi.useRealTimers(); });

describe('canActivate', () => {
  it('unknown or empty roles show the prompt', () => {
    expect(canActivate([], ['Farmer'])).toBe(true);
    expect(canActivate(['Farmer'], [])).toBe(true);
  });
  it('known roles must intersect', () => {
    expect(canActivate(['Farmer'], ['Farmer', 'TenantAdmin'])).toBe(true);
    expect(canActivate(['Viewer'], ['Farmer', 'TenantAdmin'])).toBe(false);
  });
});

describe('resolveMonitoringPrompt', () => {
  it('asks vegetation with the cookie and the encoded urn, returns the start date', async () => {
    const f = vi.fn().mockResolvedValue(state());
    expect(await resolveMonitoringPrompt('sowing', PARCEL, ['Farmer'], f)).toEqual({ start: '2026-11-18' });
    const [url, init] = f.mock.calls[0];
    expect(url).toContain(`/api/vegetation/parcels/${encodeURIComponent(PARCEL)}/monitoring`);
    expect(init.credentials).toBe('include');
  });
  it('never calls vegetation for other operations', async () => {
    const f = vi.fn();
    for (const k of ['harvesting', 'uprooting'] as const) expect(await resolveMonitoringPrompt(k, PARCEL, [], f)).toBeNull();
    expect(f).not.toHaveBeenCalled();
  });
  it('no parcel id: no call', async () => {
    const f = vi.fn();
    expect(await resolveMonitoringPrompt('sowing', '', [], f)).toBeNull();
    expect(f).not.toHaveBeenCalled();
  });
  it('needs_activation false, 404, 500 and network errors fall back to null', async () => {
    expect(await resolveMonitoringPrompt('sowing', PARCEL, [], vi.fn().mockResolvedValue(state({ needs_activation: false })))).toBeNull();
    expect(await resolveMonitoringPrompt('sowing', PARCEL, [], vi.fn().mockResolvedValue(json(404)))).toBeNull();
    expect(await resolveMonitoringPrompt('sowing', PARCEL, [], vi.fn().mockResolvedValue(json(500)))).toBeNull();
    expect(await resolveMonitoringPrompt('sowing', PARCEL, [], vi.fn().mockRejectedValue(new Error('net')))).toBeNull();
  });
  it('malformed body or missing start falls back to null', async () => {
    expect(await resolveMonitoringPrompt('sowing', PARCEL, [], vi.fn().mockResolvedValue(state({ period: null })))).toBeNull();
    const bad = { status: 200, ok: true, json: async () => { throw new Error('x'); } } as unknown as Response;
    expect(await resolveMonitoringPrompt('sowing', PARCEL, [], vi.fn().mockResolvedValue(bad))).toBeNull();
  });
  it('times out after 5 s even if fetch never settles', async () => {
    vi.useFakeTimers();
    const p = resolveMonitoringPrompt('sowing', PARCEL, [], vi.fn().mockReturnValue(new Promise(() => {})));
    await vi.advanceTimersByTimeAsync(5001);
    expect(await p).toBeNull();
  });
  it('known roles without permission: no prompt', async () => {
    const f = vi.fn().mockResolvedValue(state());
    expect(await resolveMonitoringPrompt('sowing', PARCEL, ['Viewer'], f)).toBeNull();
  });
});

describe('activateMonitoring', () => {
  it.each([[201, 'ok'], [502, 'pending'], [403, 'forbidden'], [500, 'error']])('%i -> %s', async (status, want) => {
    const f = vi.fn().mockResolvedValue(json(status));
    expect(await activateMonitoring(PARCEL, f)).toBe(want);
    const [url, init] = f.mock.calls[0];
    expect(url).toContain(`/api/entities/parcels/${encodeURIComponent(PARCEL)}/modules/vegetation-prime/activate`);
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('include');
  });
  it('network error -> error', async () => {
    expect(await activateMonitoring(PARCEL, vi.fn().mockRejectedValue(new Error('net')))).toBe('error');
  });
});
