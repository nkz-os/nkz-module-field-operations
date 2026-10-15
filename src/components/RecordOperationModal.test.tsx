import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@nekazari/sdk', () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { language: 'es' } }),
}));

import { RecordFormView, localToday, type RecordFormViewProps } from './RecordOperationModal';
import type { RecordTarget } from '../lib/recordModel';

const target: RecordTarget = { parcelId: 'urn:ngsi-ld:AgriParcel:b', parcelName: 'Soto Alto', cropId: 'c1',
  species: 'TRZAX', role: 'main_crop', variety: 'KWS KEITUM', campaign: 2027, plannedStart: '2026-11-01', name: null };

const view = (over: Partial<RecordFormViewProps>) => renderToStaticMarkup(
  <RecordFormView kind="sowing" loading={false} loadError={false} targets={[target]} names={{ TRZAX: 'trigo' }}
    form={{ parcelId: '', cropId: '', date: '2026-11-20', variety: '', seedingRate: '', sowingMethod: '', harvestedWeight: '' }}
    today="2026-11-20" saving={false} error={null} onChange={() => {}} onSubmit={() => {}} onClose={() => {}}
    onRetry={() => {}} {...over} />);

describe('RecordFormView', () => {
  it('sowing: crop list with the crop name, date capped at today, sowing fields', () => {
    const h = view({});
    expect(h).toContain('record.titleSowing');
    expect(h).toContain('Soto Alto — trigo');
    expect(h).toContain('max="2026-11-20"');
    expect(h).toContain('record.seedingRate');
    expect(h).not.toContain('record.harvestedWeight');
  });
  it('harvest: only the weight', () => {
    const h = view({ kind: 'harvesting' });
    expect(h).toContain('record.titleHarvest');
    expect(h).toContain('record.harvestedWeight');
    expect(h).not.toContain('record.seedingRate');
  });
  it('no crop to sow says where to plan it', () => {
    expect(view({ targets: [] })).toContain('record.noTargetsSowing');
  });
  it('shows the server reason and keeps the form', () => {
    const h = view({ error: 'No hay ningún cultivo planificado' });
    expect(h).toContain('role="alert"');
    expect(h).toContain('No hay ningún cultivo planificado');
  });
  it('submit stays disabled until a crop is chosen', () => {
    expect(view({})).toMatch(/id="record-submit"[^>]*\sdisabled=""/);
    expect(view({ form: { parcelId: 'p', cropId: 'c1', date: '2026-11-20', variety: '', seedingRate: '180',
      sowingMethod: '', harvestedWeight: '' } })).not.toMatch(/id="record-submit"[^>]*\sdisabled=""/);
  });
  it('load error offers a retry', () => {
    expect(view({ loadError: true })).toContain('record.loadError');
  });
});

describe('localToday', () => {
  it('is the local calendar day', () => {
    expect(localToday(new Date(2026, 10, 20, 23, 30))).toBe('2026-11-20');
  });
});
