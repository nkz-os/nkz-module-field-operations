import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { API_ORIGIN } from '../lib/apiOrigin';
import { summaryRows } from '../lib/planSummary';

type State =
  | { status: 'loading' }
  | { status: 'not_configured' | 'no_plan' | 'unavailable' }
  | { status: 'ok'; summary: any };

const dash = (x: number | null) => (x === null ? '—' : String(x));

const PlanSummaryPanel: React.FC<{ parcelId: string; campaign: number }> = ({ parcelId, campaign }) => {
  const { t } = useTranslation('field-operations');
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let alive = true;
    setState({ status: 'loading' });
    const params = new URLSearchParams({ parcel_id: parcelId, campaign: String(campaign) });
    fetch(`${API_ORIGIN}/api/field-operations/plan-summary?${params}`, { credentials: 'include' })
      .then(r => (r.ok ? r.json() : { status: 'unavailable' }))
      .catch(() => ({ status: 'unavailable' }))
      .then(body => { if (alive) setState(body as State); });
    return () => { alive = false; };
  }, [parcelId, campaign]);

  if (state.status === 'not_configured') return null;
  return (
    <div className="mt-4 border-t border-nkz-border">
      <h3 className="text-xs font-semibold text-nkz-text-muted uppercase tracking-wide mt-2 mb-2">
        {t('planSummary.title', { campaign })}
      </h3>
      {state.status === 'loading' && <p className="text-sm text-nkz-text-muted">{t('loading')}</p>}
      {state.status === 'no_plan' && <p className="text-sm text-nkz-text-muted">{t('planSummary.noPlan', { campaign })}</p>}
      {state.status === 'unavailable' && <p className="text-sm text-nkz-text-muted">{t('planSummary.unavailable')}</p>}
      {state.status === 'ok' && (() => {
        const s = state.summary;
        const sig = s.signature ?? {};
        return (
          <div className="space-y-2">
            <p className="text-xs text-nkz-text-muted">
              {t('planSummary.signed', { date: (s.signed_at ?? '').slice(0, 10), version: s.version })}
              {' · '}
              {sig.kind === 'advisor'
                ? t('planSummary.byAdvisor', { name: sig.name, number: sig.registration_number })
                : t('planSummary.byHolder', { name: sig.name })}
            </p>
            {summaryRows(s).map(row => (
              <dl key={row.key} className="grid grid-cols-2 gap-2 text-sm">
                <dt className="text-xs text-nkz-text-muted">{t('planSummary.crop')}</dt>
                <dd className="text-nkz-text-primary">{row.crop ?? '—'}</dd>
                <dt className="text-xs text-nkz-text-muted">{t('planSummary.previous')}</dt>
                <dd className="text-nkz-text-primary">{row.previous ?? '—'}</dd>
                <dt className="text-xs text-nkz-text-muted">{t('planSummary.yield')}</dt>
                <dd className="text-nkz-text-primary">{dash(row.yieldKgHa)}</dd>
                <dt className="text-xs text-nkz-text-muted">{t('planSummary.n')}</dt>
                <dd className="text-nkz-text-primary">{dash(row.n.min)} / {dash(row.n.avg)} / {dash(row.n.max)}</dd>
                <dt className="text-xs text-nkz-text-muted">{t('planSummary.p2o5')}</dt>
                <dd className="text-nkz-text-primary">{dash(row.p2o5)}</dd>
                <dt className="text-xs text-nkz-text-muted">{t('planSummary.k2o')}</dt>
                <dd className="text-nkz-text-primary">{dash(row.k2o)}</dd>
              </dl>
            ))}
            <a href={`${API_ORIGIN}/api/fast/plans/${encodeURIComponent(s.plan_id)}/pdf`}
               target="_blank" rel="noopener noreferrer"
               className="text-xs text-nkz-accent-base hover:underline">
              {t('planSummary.pdf')}
            </a>
          </div>
        );
      })()}
    </div>
  );
};

export default PlanSummaryPanel;
