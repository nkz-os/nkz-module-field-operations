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
  const flagged = { type: 'Relationship', object: ['urn:a', 'urn:b'] };
  const review = (ids: string[]) => ({ type: 'Property', value: { decision: 'keep_both', reviewed: ids } });
  const check = (f: unknown, r: unknown, status = 'completed', src = 'sensor', type = 'irrigation') =>
    needsDuplicateReview(status, src, type, f, r);

  it('is true when flagged and never reviewed', () => {
    expect(check(flagged, undefined)).toBe(true);
  });
  it('is true while any flagged id is not in reviewed', () => {
    expect(check(flagged, review(['urn:a']))).toBe(true);
  });
  it('is false once every flagged id is reviewed', () => {
    expect(check(flagged, review(['urn:b', 'urn:a']))).toBe(false);
    expect(check({ type: 'Property', value: ['urn:a'] }, review(['urn:a']))).toBe(false);
  });
  it('counts an old plain-string review as nothing reviewed', () => {
    expect(check(flagged, { type: 'Property', value: 'keep_both' })).toBe(true);
  });
  it('is false when unflagged or not a live sensor irrigation', () => {
    expect(check(undefined, undefined)).toBe(false);
    expect(check(flagged, undefined, 'cancelled')).toBe(false);
    expect(check(flagged, undefined, 'completed', 'manual')).toBe(false);
    expect(check(flagged, undefined, 'completed', 'sensor', 'spraying')).toBe(false);
  });
});
