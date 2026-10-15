import { describe, expect, it } from 'vitest';
import { buildRecordBody, cropNamesFromFarm, errorKey, targetsFor, type ParcelView } from './recordModel';

const parcels: ParcelView[] = [
  { id: 'urn:ngsi-ld:AgriParcel:b', name: 'Soto Alto', area: 12, readable: true, cycles: [
    { crop_id: 'c1', species: 'TRZAX', role: 'main_crop', variety: 'KWS KEITUM', campaign_label: 2027,
      start: { date: '2026-11-01', provenance: 'planned' }, end: { date: null, provenance: null },
      can_sow: true, can_harvest: false },
    { crop_id: 'c0', species: 'HORVX', role: 'main_crop', variety: null, campaign_label: 2026,
      start: { date: '2025-11-10', provenance: 'actual' }, end: { date: '2026-07-31', provenance: 'planned' },
      can_sow: false, can_harvest: true },
  ] },
  { id: 'urn:ngsi-ld:AgriParcel:a', name: 'El Raso', area: 3, readable: true, cycles: [] },
];

describe('targetsFor', () => {
  it('lists only the crops that can take that record, one per crop', () => {
    expect(targetsFor(parcels, 'sowing').map((t) => t.cropId)).toEqual(['c1']);
    expect(targetsFor(parcels, 'harvesting').map((t) => t.cropId)).toEqual(['c0']);
  });
  it('carries what the form pre-fills', () => {
    const [t] = targetsFor(parcels, 'sowing');
    expect(t).toMatchObject({ parcelId: 'urn:ngsi-ld:AgriParcel:b', parcelName: 'Soto Alto', species: 'TRZAX',
      variety: 'KWS KEITUM', campaign: 2027, plannedStart: '2026-11-01' });
  });
});

describe('buildRecordBody', () => {
  it('sowing: numbers as numbers, empty optionals left out', () => {
    expect(buildRecordBody('sowing', { parcelId: 'p', cropId: 'c1', date: '2026-11-10', variety: ' Califa ',
      seedingRate: '180', sowingMethod: '', harvestedWeight: '' })).toEqual({
      operation_type: 'sowing', parcel_id: 'p', crop_id: 'c1', date: '2026-11-10', variety: 'Califa', seedingRate: 180 });
  });
  it('harvest: only the weight', () => {
    expect(buildRecordBody('harvesting', { parcelId: 'p', cropId: 'c0', date: '2026-07-02', variety: 'x',
      seedingRate: '9', sowingMethod: 'direct', harvestedWeight: '41000' })).toEqual({
      operation_type: 'harvesting', parcel_id: 'p', crop_id: 'c0', date: '2026-07-02', harvestedWeight: 41000 });
  });
});

describe('errorKey', () => {
  it('maps server codes to messages, unknown to a generic one', () => {
    expect(errorKey('no_planned_crop')).toBe('record.error.no_planned_crop');
    expect(errorKey('date_outside_crop_window')).toBe('record.error.date_outside_crop_window');
    expect(errorKey('weird')).toBe('record.error.generic');
    expect(errorKey(undefined)).toBe('record.error.generic');
  });
});

describe('cropNamesFromFarm', () => {
  it('maps the planning codes to names in the user language, falling back to Spanish', () => {
    const farm = { parcels: [{ cells: { '2027': [{ species_raw: 'TRZAX', names: { es: 'trigo', en: 'wheat' } }],
      '2026': [{ species_raw: 'HORVX', names: { es: 'cebada' } }, { species_raw: null, names: {} }] } }] };
    expect(cropNamesFromFarm(farm, 'en')).toEqual({ TRZAX: 'wheat', HORVX: 'cebada' });
  });
  it('is empty on anything unexpected', () => {
    expect(cropNamesFromFarm(null, 'es')).toEqual({});
    expect(cropNamesFromFarm({ parcels: 'x' }, 'es')).toEqual({});
  });
});

import { bearerHeaders, canSubmit, cropLabel, selectTarget } from './recordModel';

describe('selectTarget', () => {
  const ts = targetsFor(parcels, 'sowing').concat([{ parcelId: 'p2', parcelName: 'X', cropId: 'c9', species: 'ZEAMX',
    role: 'main_crop', variety: null, campaign: 2027, plannedStart: null, name: null }]);
  const base = { parcelId: '', cropId: '', date: '2026-11-20', variety: '', seedingRate: '', sowingMethod: '', harvestedWeight: '' };
  it('pre-fills the planned variety and clears it for a crop without one', () => {
    const a = selectTarget(base, ts, 'c1');
    expect(a).toMatchObject({ cropId: 'c1', parcelId: 'urn:ngsi-ld:AgriParcel:b', variety: 'KWS KEITUM' });
    expect(selectTarget(a, ts, 'c9').variety).toBe('');
    expect(selectTarget(a, ts, '')).toMatchObject({ cropId: '', parcelId: '', variety: '' });
  });
});

describe('canSubmit', () => {
  const f = { parcelId: 'p', cropId: 'c1', date: '2026-11-10', variety: 'v', seedingRate: '180', sowingMethod: '', harvestedWeight: '' };
  it('needs a crop, a date and the positive numbers of that kind', () => {
    expect(canSubmit('sowing', f)).toBe(true);
    expect(canSubmit('sowing', { ...f, seedingRate: '180,5' })).toBe(true);
    expect(canSubmit('sowing', { ...f, seedingRate: 'abc' })).toBe(false);
    expect(canSubmit('sowing', { ...f, seedingRate: '0' })).toBe(false);
    expect(canSubmit('sowing', { ...f, cropId: '' })).toBe(false);
    expect(canSubmit('harvesting', { ...f, harvestedWeight: '41000' })).toBe(true);
    expect(canSubmit('harvesting', { ...f, harvestedWeight: '' })).toBe(false);
  });
});

describe('cropLabel', () => {
  it('prefers the planning name, then the crop name, then the code', () => {
    expect(cropLabel({ species: 'TRZAX', name: 'trigo blando' }, { TRZAX: 'trigo' })).toBe('trigo');
    expect(cropLabel({ species: 'TRZAX', name: 'trigo blando' }, {})).toBe('trigo blando');
    expect(cropLabel({ species: 'TRZAX', name: null }, {})).toBe('TRZAX');
  });
});

describe('bearerHeaders', () => {
  it('sends the session token planning requires, nothing without one', () => {
    expect(bearerHeaders({ keycloak: { token: 'abc' } })).toEqual({ Authorization: 'Bearer abc' });
    expect(bearerHeaders({})).toEqual({});
  });
});

describe('errorKey (new codes)', () => {
  it('knows the store, parcel, number and perennial codes', () => {
    for (const c of ['store_unavailable', 'invalid_parcel', 'invalid_number', 'perennial_harvest_unsupported']) {
      expect(errorKey(c)).toBe(`record.error.${c}`);
    }
  });
});
