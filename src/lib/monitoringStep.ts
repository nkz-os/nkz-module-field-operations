import type { ActivationResult } from './monitoringPrompt';

export type MonitoringPhase = 'idle' | 'checking' | 'prompt' | 'activating' | 'result' | 'closed';

export interface MonitoringStepState {
  phase: MonitoringPhase;
  message: string;
  parcelId: string;
  start: string | null;
  result: ActivationResult | null;
}

export type MonitoringAction =
  | { type: 'recorded'; message: string; parcelId: string }
  | { type: 'checked'; start: string | null }
  | { type: 'activate' }
  | { type: 'activated'; result: ActivationResult }
  | { type: 'close' };

export const INITIAL_STEP: MonitoringStepState = { phase: 'idle', message: '', parcelId: '', start: null, result: null };

/**
 * Steps of the modal after the sowing was saved. `notify` is true exactly once per recorded
 * operation, on the transition to `closed`: that is when onRecorded must be called.
 */
export function monitoringStep(s: MonitoringStepState, a: MonitoringAction): { state: MonitoringStepState; notify: boolean } {
  const stay = { state: s, notify: false };
  switch (a.type) {
    case 'recorded':
      return s.phase === 'idle' ? { state: { ...s, phase: 'checking', message: a.message, parcelId: a.parcelId }, notify: false } : stay;
    case 'checked':
      if (s.phase !== 'checking') return stay;
      return a.start
        ? { state: { ...s, phase: 'prompt', start: a.start }, notify: false }
        : { state: { ...s, phase: 'closed' }, notify: true };
    case 'activate':
      return s.phase === 'prompt' ? { state: { ...s, phase: 'activating' }, notify: false } : stay;
    case 'activated':
      return s.phase === 'activating' ? { state: { ...s, phase: 'result', result: a.result }, notify: false } : stay;
    case 'close':
      // checking: the record is saved, the dashboard must still refresh. prompt: "not now".
      return s.phase === 'checking' || s.phase === 'prompt' || s.phase === 'result'
        ? { state: { ...s, phase: 'closed' }, notify: true } : stay;
    default:
      return stay;
  }
}
