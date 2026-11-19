import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import type { ActivationResult } from '../lib/monitoringPrompt';

export interface MonitoringPromptViewProps {
  start: string;
  busy: boolean;
  result: ActivationResult | null;
  onActivate: () => void;
  onSkip: () => void;
}

/** Second step of the sowing modal: offer satellite monitoring from the sowing date. */
export function MonitoringPromptView(p: MonitoringPromptViewProps) {
  const { t, i18n } = useTranslation('field-operations');
  const parsed = new Date(`${p.start.slice(0, 10)}T00:00:00`);
  const date = Number.isNaN(parsed.getTime()) ? p.start : parsed.toLocaleDateString(i18n?.language || undefined);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="relative bg-nkz-surface rounded-xl shadow-2xl w-full max-w-lg mx-4 flex flex-col">
        <div className="p-4 border-b border-nkz-border">
          <h2 className="text-nkz-text-primary font-bold text-base">{t('monitoring.title')}</h2>
        </div>
        <div className="p-4 space-y-2">
          <p className="text-sm text-nkz-text-primary">{t('monitoring.body', { date })}</p>
          {p.result && (
            <p role="status" className={`text-sm ${p.result === 'ok' || p.result === 'pending' ? 'text-nkz-text-muted' : 'text-nkz-danger'}`}>
              {t(`monitoring.result.${p.result}`)}
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2 p-4 border-t border-nkz-border">
          <button id="monitoring-skip" type="button" onClick={p.onSkip} disabled={p.busy}
            className="text-sm text-nkz-text-muted hover:text-nkz-text-primary px-3 py-1.5">
            {t('monitoring.skip')}
          </button>
          <button id="monitoring-activate" type="button" onClick={p.onActivate} disabled={p.busy || p.result !== null}
            className="text-sm font-medium rounded-md px-3 py-1.5 bg-nkz-accent-base text-white disabled:opacity-50">
            {t('monitoring.activate')}
          </button>
        </div>
      </div>
    </div>
  );
}
