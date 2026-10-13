import type { Operation } from '../components/OperationCard';

/** Harvest-year campaign of a day: the agricultural year runs 1-Sep..31-Aug (FaST, art. 4.2). */
export function campaignOf(day: Date): number {
  return day.getMonth() >= 8 ? day.getFullYear() + 1 : day.getFullYear();
}

function dateValue(attr: unknown): Date | null {
  const raw = (attr as { value?: unknown } | undefined)?.value;
  const text = typeof raw === 'string' ? raw : (raw as { '@value'?: string } | undefined)?.['@value'];
  if (!text) return null;
  const day = new Date(text);
  return Number.isNaN(day.getTime()) ? null : day;
}

/** The day an operation belongs to: when it ended, started or was planned; otherwise now. */
export function operationDay(op: Operation, now: Date = new Date()): Date {
  const record = op as unknown as Record<string, unknown>;
  return dateValue(record.endedAt) ?? dateValue(record.startedAt) ?? dateValue(record.plannedDate) ?? now;
}

const round = (x: unknown): number | null =>
  typeof x === 'number' && Number.isFinite(x) ? Math.round(x) : null;

export interface SummaryRow {
  key: string; crop: string | null; previous: string | null; yieldKgHa: number | null;
  n: { min: number | null; avg: number | null; max: number | null };
  p2o5: number | null; k2o: number | null;
}

export function summaryRows(summary: { sheets?: Array<Record<string, any>> }): SummaryRow[] {
  return (summary?.sheets ?? []).map(s => ({
    key: String(s.key),
    crop: s.crop_eppo ?? null,
    previous: s.previous_crop_eppo ?? null,
    yieldKgHa: round(s.expected_yield_kg_ha),
    n: { min: round(s.n_kg_ha?.min), avg: round(s.n_kg_ha?.avg), max: round(s.n_kg_ha?.max) },
    p2o5: round(s.p2o5_kg_ha),
    k2o: round(s.k2o_kg_ha),
  }));
}
