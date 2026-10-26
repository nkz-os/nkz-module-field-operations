import { describe, expect, it } from 'vitest';
import {
  duplicateChoices, needsDuplicateReview, parseSensorConflict, withSensorOverlap,
} from './duplicateWarning';

describe('parseSensorConflict', () => {
  it('reads the 409 detail of an existing meter record', () => {
    expect(parseSensorConflict({
      code: 'sensor_irrigation_exists', detail: 'x', sensorWaterPerHectare: 1500, day: '2026-10-25',
    })).toEqual({ waterPerHectare: 1500, day: '2026-10-25' });
  });
  it('is null for any other error', () => {
    expect(parseSensorConflict({ code: 'future_date' })).toBeNull();
    expect(parseSensorConflict('HTTP 409')).toBeNull();
    expect(parseSensorConflict(undefined)).toBeNull();
  });
  it('keeps an unknown dose as null', () => {
    expect(parseSensorConflict({ code: 'sensor_irrigation_exists' })?.waterPerHectare).toBeNull();
  });
});

describe('duplicateChoices', () => {
  it('always offers keep both; replace only to managers', () => {
    expect(duplicateChoices(false)).toEqual(['keep_both']);
    expect(duplicateChoices(true)).toEqual(['keep_both', 'replace_sensor']);
  });
});

describe('withSensorOverlap', () => {
  it('adds the choice without touching the rest', () => {
    expect(withSensorOverlap({ a: 1 }, 'keep_both')).toEqual({ a: 1, sensorOverlap: 'keep_both' });
  });
});

describe('needsDuplicateReview', () => {
  const flagged = { object: ['urn:x'] };
  it('is true for a completed sensor irrigation flagged and not reviewed', () => {
    expect(needsDuplicateReview('completed', 'sensor', 'irrigation', flagged, undefined)).toBe(true);
  });
  it('is false once reviewed, unflagged, or not a live sensor irrigation', () => {
    expect(needsDuplicateReview('completed', 'sensor', 'irrigation', flagged, { value: 'keep_both' })).toBe(false);
    expect(needsDuplicateReview('completed', 'sensor', 'irrigation', undefined, undefined)).toBe(false);
    expect(needsDuplicateReview('cancelled', 'sensor', 'irrigation', flagged, undefined)).toBe(false);
    expect(needsDuplicateReview('completed', 'manual', 'irrigation', flagged, undefined)).toBe(false);
    expect(needsDuplicateReview('completed', 'sensor', 'spraying', flagged, undefined)).toBe(false);
  });
});
