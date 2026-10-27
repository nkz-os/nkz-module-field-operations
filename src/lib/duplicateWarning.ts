// Manual and water-meter irrigation recorded on the same parcel and day.
import { canCorrectSensorOperation } from './sensorOperation';

export type SensorOverlap = 'keep_both' | 'replace_sensor';

export interface SensorConflict {
  waterPerHectare: number | null;
  day: string | null;
}

/** The 409 `sensor_irrigation_exists` detail of a completion, or null for any other error. */
export function parseSensorConflict(detail: unknown): SensorConflict | null {
  if (!detail || typeof detail !== 'object') return null;
  const d = detail as Record<string, unknown>;
  if (d.code !== 'sensor_irrigation_exists') return null;
  return {
    waterPerHectare: typeof d.sensorWaterPerHectare === 'number' ? d.sensorWaterPerHectare : null,
    day: typeof d.day === 'string' ? d.day : null,
  };
}

/** What the warning offers: keep both always, replace the meter record only to managers. */
export function duplicateChoices(isManager: boolean): SensorOverlap[] {
  return isManager ? ['keep_both', 'replace_sensor'] : ['keep_both'];
}

export function withSensorOverlap(
  body: Record<string, unknown>, choice: SensorOverlap,
): Record<string, unknown> {
  return { ...body, sensorOverlap: choice };
}

function unwrap(attr: unknown): unknown {
  if (attr && typeof attr === 'object' && !Array.isArray(attr)) {
    const a = attr as Record<string, unknown>;
    if ('object' in a) return a.object;
    if ('value' in a) return a.value;
  }
  return attr;
}

/** The ids a flag points at, from a normalized attribute or a bare keyValues one. */
function flaggedIds(attr: unknown): string[] {
  const v = unwrap(attr);
  const list = Array.isArray(v) ? v : v ? [v] : [];
  return list.filter((x): x is string => typeof x === 'string');
}

/** The ids a review covered; an old plain-string review covered none. */
function reviewedIds(attr: unknown): string[] {
  const v = unwrap(attr);
  if (v && typeof v === 'object' && Array.isArray((v as { reviewed?: unknown }).reviewed)) {
    return (v as { reviewed: unknown[] }).reviewed.filter((x): x is string => typeof x === 'string');
  }
  return [];
}

/** A meter record flagged as a possible duplicate where some flagged id has not been reviewed. */
export function needsDuplicateReview(
  status: string, dataSource: string, operationType: string,
  possibleDuplicateOf: unknown, duplicateReview: unknown,
): boolean {
  if (!canCorrectSensorOperation(status, dataSource, operationType)) return false;
  const reviewed = new Set(reviewedIds(duplicateReview));
  return flaggedIds(possibleDuplicateOf).some(id => !reviewed.has(id));
}
