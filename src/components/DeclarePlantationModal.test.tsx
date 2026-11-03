import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'es' } }),
}));

import { DeclarePlantationView, dateBounds, type DeclarePlantationViewProps } from './DeclarePlantationModal';
import { buildPlantationBody, plantationErrorKey } from '../lib/recordModel';

const view = (over: Partial<DeclarePlantationViewProps>) => renderToStaticMarkup(
  <DeclarePlantationView loading={false} loadError={false} parcels={[{ id: 'urn:ngsi-ld:AgriParcel:p1', name: 'Soto' }]}
    form={{ parcelId: '', eppo: '', year: '', date: '', variety: '' }} today="2026-11-03" saving={false}
    error={null} onChange={() => {}} onSubmit={() => {}} onClose={() => {}} onRetry={() => {}} {...over} />);

describe('DeclarePlantationView', () => {
  it('asks for species (common names), year, optional day and variety', () => {
    const h = view({});
    expect(h).toContain('plantation.title');
    expect(h).toContain('>plantation.speciesNames.OLVEU<');
    expect(h).toContain('value="VITVI"');
    expect(h).toContain('max="2026-11-03"');
    expect(h).toContain('id="plantation-year"');
    expect(h).toContain('id="plantation-variety"');
  });
  it('submit stays disabled until parcel, species and a 4-digit year are set', () => {
    expect(view({})).toMatch(/id="plantation-submit"[^>]*\sdisabled=""/);
    expect(view({ form: { parcelId: 'p', eppo: 'OLVEU', year: '2015', date: '', variety: '' } }))
      .not.toMatch(/id="plantation-submit"[^>]*\sdisabled=""/);
  });
  it('declare plantation posts eppo and year', () => {
    expect(buildPlantationBody({ parcelId: 'p', eppo: 'OLVEU', year: '2015', date: '', variety: '' }))
      .toEqual({ eppo: 'OLVEU', planting_year: 2015 });
  });
  it('maps 409 parcel_has_current_crop to its message', () => {
    expect(plantationErrorKey('parcel_has_current_crop')).toBe('plantation.errors.parcel_has_current_crop');
    expect(view({ error: 'plantation.errors.parcel_has_current_crop' })).toContain('role="alert"');
  });
  it('the day input is bounded by the planting year and today', () => {
    expect(dateBounds('', '2026-11-03')).toEqual({ max: '2026-11-03' });
    expect(dateBounds('2015', '2026-11-03')).toEqual({ min: '2015-01-01', max: '2015-12-31' });
    expect(dateBounds('2026', '2026-11-03')).toEqual({ min: '2026-01-01', max: '2026-11-03' });
    const h = view({ form: { parcelId: '', eppo: '', year: '2015', date: '', variety: '' } });
    expect(h).toContain('min="2015-01-01"');
    expect(h).toContain('max="2015-12-31"');
  });
  it('maps the new refusal codes', () => {
    expect(plantationErrorKey('overlaps_recorded_crop')).toBe('plantation.errors.overlaps_recorded_crop');
    expect(plantationErrorKey('invalid_variety')).toBe('plantation.errors.invalid_variety');
  });
});
