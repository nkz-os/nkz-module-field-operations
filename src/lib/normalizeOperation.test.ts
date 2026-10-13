import { describe, expect, it } from 'vitest';
import { normalizeOperation } from './normalizeOperation';

// As the list endpoint returns it (Orion-LD, options=keyValues).
const LISTED = {
  id: 'urn:ngsi-ld:AgriParcelOperation:t:f927964276ad',
  type: 'AgriParcelOperation',
  refAgriParcel: 'urn:ngsi-ld:AgriParcel:t:p1',
  operationType: 'sowing',
  workOrder: 'WO-2',
  status: 'completed',
  operator: 'op@test',
  dataSource: 'manual',
  modificationLog: [],
  seedingRate: 180,
  startedAt: { '@type': 'DateTime', '@value': '2026-10-12T23:13:31.882795+00:00' },
  sowingMethod: 'direct',
};

// As GET /operations/{id} returns it (normalized).
const FETCHED = {
  id: 'urn:ngsi-ld:AgriParcelOperation:t:f927964276ad',
  type: 'AgriParcelOperation',
  refAgriParcel: { type: 'Relationship', object: 'urn:ngsi-ld:AgriParcel:t:p1' },
  status: { type: 'Property', value: 'completed' },
  startedAt: { type: 'Property', value: { '@type': 'DateTime', '@value': '2026-10-12T23:13:31.882795+00:00' } },
};

describe('normalizeOperation', () => {
  it('wraps keyValues attributes so the components can read .value', () => {
    const op = normalizeOperation(LISTED);
    expect(op.status?.value).toBe('completed');
    expect(op.operationType?.value).toBe('sowing');
    expect(op.workOrder?.value).toBe('WO-2');
    expect(op.startedAt?.value).toEqual({ '@type': 'DateTime', '@value': '2026-10-12T23:13:31.882795+00:00' });
    expect(op.sowingMethod).toEqual({ type: 'Property', value: 'direct' });
    expect(op.modificationLog).toEqual({ type: 'Property', value: [] });
    expect(op.seedingRate).toEqual({ type: 'Property', value: 180 });
  });

  it('keeps the entity id and type as they are', () => {
    const op = normalizeOperation(LISTED);
    expect(op.id).toBe(LISTED.id);
    expect(op.type).toBe('AgriParcelOperation');
  });

  it('exposes the parcel as hasAgriParcel.object whichever name Orion answers with', () => {
    expect(normalizeOperation(LISTED).hasAgriParcel?.object).toBe('urn:ngsi-ld:AgriParcel:t:p1');
    expect(normalizeOperation(FETCHED).hasAgriParcel?.object).toBe('urn:ngsi-ld:AgriParcel:t:p1');
  });

  it('leaves attributes that are already normalized untouched', () => {
    const op = normalizeOperation(FETCHED);
    expect(op.status).toEqual(FETCHED.status);
    expect(op.startedAt).toEqual(FETCHED.startedAt);
    expect(op.refAgriParcel).toEqual(FETCHED.refAgriParcel);
  });
});
