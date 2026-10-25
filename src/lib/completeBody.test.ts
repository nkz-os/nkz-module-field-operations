import { describe, expect, it } from 'vitest';
import { buildCompleteBody, localDay } from './completeBody';

describe('localDay', () => {
  it('formats the local calendar day, not the UTC one', () => {
    expect(localDay(new Date(2026, 9, 5, 23, 30))).toBe('2026-10-05');
  });
});

describe('buildCompleteBody', () => {
  it('carries the chosen day as completedOn next to the form fields', () => {
    expect(buildCompleteBody({ tillageType: 'plough' }, '2026-10-20'))
      .toEqual({ tillageType: 'plough', completedOn: '2026-10-20' });
  });
  it('omits completedOn when no day is chosen', () => {
    expect(buildCompleteBody({ a: 1 }, '')).toEqual({ a: 1 });
  });
});
