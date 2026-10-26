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

/** A meter record flagged as a possible duplicate that nobody has reviewed yet. */
export function needsDuplicateReview(
  status: string, dataSource: string, operationType: string,
  possibleDuplicateOf: unknown, duplicateReview: unknown,
): boolean {
  return canCorrectSensorOperation(status, dataSource, operationType)
    && Boolean(possibleDuplicateOf) && !duplicateReview;
}
