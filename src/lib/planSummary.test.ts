import { describe, expect, it } from 'vitest';
import { campaignOf, operationDay, summaryRows } from './planSummary';

describe('campaignOf', () => {
  it('maps the agricultural year to its harvest year', () => {
    expect(campaignOf(new Date(2026, 8, 1))).toBe(2027);
    expect(campaignOf(new Date(2026, 7, 31))).toBe(2026);
    expect(campaignOf(new Date(2027, 0, 15))).toBe(2027);
  });
});

describe('operationDay', () => {
  const now = new Date(2026, 9, 13);
  it('prefers endedAt, then startedAt, then plannedDate', () => {
    expect(operationDay({ endedAt: { value: { '@value': '2027-02-10T09:00:00Z' } } } as any, now)
      .getFullYear()).toBe(2027);
    expect(operationDay({ startedAt: { value: '2026-09-05T09:00:00Z' } } as any, now).getMonth()).toBe(8);
    expect(operationDay({ plannedDate: { value: { '@value': '2026-11-02' } } } as any, now).getMonth()).toBe(10);
  });
  it('falls back to now', () => {
    expect(operationDay({} as any, now)).toBe(now);
  });
});

describe('summaryRows', () => {
  it('rounds and keeps missing values as null', () => {
    const rows = summaryRows({ sheets: [{ key: 'w', crop_eppo: 'TRZAX', previous_crop_eppo: null,
      expected_yield_kg_ha: 5600.4, n_kg_ha: { min: 99.6, avg: 130.2, max: null },
      p2o5_kg_ha: 45.0, k2o_kg_ha: null }] });
    expect(rows).toEqual([{ key: 'w', crop: 'TRZAX', previous: null, yieldKgHa: 5600,
      n: { min: 100, avg: 130, max: null }, p2o5: 45, k2o: null }]);
  });
  it('tolerates a summary without sheets', () => {
    expect(summaryRows({} as any)).toEqual([]);
  });
});
