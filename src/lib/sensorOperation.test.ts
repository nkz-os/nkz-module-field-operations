import { describe, expect, it } from 'vitest';
import { canCorrectSensorOperation } from './sensorOperation';

describe('canCorrectSensorOperation', () => {
  it('is true only for completed sensor irrigation', () => {
    expect(canCorrectSensorOperation('completed', 'sensor', 'irrigation')).toBe(true);
    expect(canCorrectSensorOperation('incomplete', 'sensor', 'irrigation')).toBe(false);
    expect(canCorrectSensorOperation('cancelled', 'sensor', 'irrigation')).toBe(false);
    expect(canCorrectSensorOperation('completed', 'manual', 'irrigation')).toBe(false);
    expect(canCorrectSensorOperation('completed', 'mixed', 'irrigation')).toBe(false);
    expect(canCorrectSensorOperation('completed', 'sensor', 'spraying')).toBe(false);
  });
});
