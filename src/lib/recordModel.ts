/** Recording a sowing or a harvest that already happened (pure helpers for the record form). */

export type RecordKind = 'sowing' | 'harvesting';

export interface Boundary {
  date: string | null;
  provenance: string | null;
}

export interface CycleView {
  crop_id: string;
  species: string | null;
  role: string;
  variety: string | null;
  campaign_label: number | null;
  start: Boundary;
  end: Boundary;
  can_sow: boolean;
  can_harvest: boolean;
}

export interface ParcelView {
  id: string;
  name: string | null;
  area: number | null;
  readable: boolean;
  cycles: CycleView[];
}

export interface RecordTarget {
  parcelId: string;
  parcelName: string;
  cropId: string;
  species: string | null;
  role: string;
  variety: string | null;
  campaign: number | null;
  plannedStart: string | null;
}

export interface RecordForm {
  parcelId: string;
  cropId: string;
  date: string;
  variety: string;
  seedingRate: string;
  sowingMethod: string;
  harvestedWeight: string;
}

/** The crops that can take this kind of record now, one entry per crop. */
export function targetsFor(parcels: ParcelView[], kind: RecordKind): RecordTarget[] {
  const out: RecordTarget[] = [];
  for (const p of parcels) {
    for (const c of p.cycles) {
      if (kind === 'sowing' ? !c.can_sow : !c.can_harvest) continue;
      out.push({
        parcelId: p.id, parcelName: p.name ?? p.id, cropId: c.crop_id, species: c.species, role: c.role,
        variety: c.variety, campaign: c.campaign_label, plannedStart: c.start.date,
      });
    }
  }
  return out;
}

function num(raw: string): number | undefined {
  const v = Number(String(raw).replace(',', '.'));
  return raw.trim() !== '' && Number.isFinite(v) ? v : undefined;
}

/** The POST /operations/record body: only the fields of that kind, numbers as numbers. */
export function buildRecordBody(kind: RecordKind, f: RecordForm): Record<string, unknown> {
  const body: Record<string, unknown> = {
    operation_type: kind, parcel_id: f.parcelId, crop_id: f.cropId, date: f.date,
  };
  if (kind === 'sowing') {
    if (f.variety.trim()) body.variety = f.variety.trim();
    const rate = num(f.seedingRate);
    if (rate !== undefined) body.seedingRate = rate;
    if (f.sowingMethod) body.sowingMethod = f.sowingMethod;
  } else {
    const weight = num(f.harvestedWeight);
    if (weight !== undefined) body.harvestedWeight = weight;
  }
  return body;
}

const KNOWN_ERRORS = new Set([
  'no_planned_crop', 'no_crop_to_close', 'not_sown', 'already_recorded', 'future_date',
  'date_outside_crop_window', 'missing_fields', 'invalid_date', 'parcel_not_found', 'crop_data_unavailable',
]);

/** i18n key for a server error code. */
export function errorKey(code: string | undefined): string {
  return code && KNOWN_ERRORS.has(code) ? `record.error.${code}` : 'record.error.generic';
}

/**
 * Crop names in the user's language from the planning matrix, which already carries them
 * (the platform has no other code-to-name catalogue). Best effort: empty on anything unexpected.
 */
export function cropNamesFromFarm(farm: unknown, lang: string): Record<string, string> {
  const out: Record<string, string> = {};
  const parcels = (farm as { parcels?: unknown } | null)?.parcels;
  if (!Array.isArray(parcels)) return out;
  for (const p of parcels) {
    const cells = (p as { cells?: Record<string, unknown> })?.cells;
    if (!cells || typeof cells !== 'object') continue;
    for (const list of Object.values(cells)) {
      if (!Array.isArray(list)) continue;
      for (const cell of list as { species_raw?: string | null; names?: Record<string, string> }[]) {
        const name = cell?.names?.[lang] ?? cell?.names?.es;
        if (cell?.species_raw && name && !out[cell.species_raw]) out[cell.species_raw] = name;
      }
    }
  }
  return out;
}
