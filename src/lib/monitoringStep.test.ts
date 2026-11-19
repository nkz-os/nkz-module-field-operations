import { describe, expect, it } from 'vitest';
import { INITIAL_STEP, monitoringStep, type MonitoringAction, type MonitoringStepState } from './monitoringStep';

function run(actions: MonitoringAction[]): { state: MonitoringStepState; notified: number } {
  let state = INITIAL_STEP;
  let notified = 0;
  for (const a of actions) {
    const r = monitoringStep(state, a);
    state = r.state;
    if (r.notify) notified += 1;
  }
  return { state, notified };
}
const rec: MonitoringAction = { type: 'recorded', message: 'm', parcelId: 'urn:ngsi-ld:AgriParcel:p1' };

describe('monitoringStep', () => {
  it('recorded -> checking, no notify yet', () => {
    const r = run([rec]);
    expect(r.state.phase).toBe('checking');
    expect(r.notified).toBe(0);
  });
  it('check with an offer -> prompt, not yet notified', () => {
    const r = run([rec, { type: 'checked', start: '2026-11-18' }]);
    expect(r.state.phase).toBe('prompt');
    expect(r.state.start).toBe('2026-11-18');
    expect(r.notified).toBe(0);
  });
  it('check without offer (failure/timeout) -> closed, notified once', () => {
    const r = run([rec, { type: 'checked', start: null }]);
    expect(r.state.phase).toBe('closed');
    expect(r.notified).toBe(1);
  });
  it('activate -> activating -> result shown, not notified until close; close notifies once', () => {
    const a = run([rec, { type: 'checked', start: '2026-11-18' }, { type: 'activate' }]);
    expect(a.state.phase).toBe('activating');
    const b = run([rec, { type: 'checked', start: '2026-11-18' }, { type: 'activate' }, { type: 'activated', result: 'forbidden' }]);
    expect(b.state.phase).toBe('result');
    expect(b.state.result).toBe('forbidden');
    expect(b.notified).toBe(0);
    const c = run([rec, { type: 'checked', start: '2026-11-18' }, { type: 'activate' }, { type: 'activated', result: 'ok' }, { type: 'close' }, { type: 'close' }]);
    expect(c.state.phase).toBe('closed');
    expect(c.notified).toBe(1);
  });
  it('not now notifies once', () => {
    const r = run([rec, { type: 'checked', start: '2026-11-18' }, { type: 'close' }, { type: 'close' }]);
    expect(r.state.phase).toBe('closed');
    expect(r.notified).toBe(1);
  });
  it('closing while checking notifies once; the late check result is ignored', () => {
    const r = run([rec, { type: 'close' }, { type: 'checked', start: '2026-11-18' }, { type: 'checked', start: null }]);
    expect(r.state.phase).toBe('closed');
    expect(r.notified).toBe(1);
  });
  it('close before anything was recorded does not notify', () => {
    expect(run([{ type: 'close' }]).notified).toBe(0);
  });
  it('close while activating is ignored', () => {
    const r = run([rec, { type: 'checked', start: 'x' }, { type: 'activate' }, { type: 'close' }]);
    expect(r.state.phase).toBe('activating');
    expect(r.notified).toBe(0);
  });
});
