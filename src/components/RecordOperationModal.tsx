import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { API_ORIGIN } from '../lib/apiOrigin';
import {
  buildRecordBody, cropNamesFromFarm, errorKey, targetsFor,
  type ParcelView, type RecordForm, type RecordKind, type RecordTarget,
} from '../lib/recordModel';

const API_BASE = `${API_ORIGIN}/api/field-operations`;
const INPUT = 'mt-0.5 block w-full rounded-md border border-nkz-border bg-nkz-background px-2 py-1.5 text-sm text-nkz-text-primary focus:outline-none focus:ring-1 focus:ring-nkz-accent-base';
const LABEL = 'text-xs font-medium text-nkz-text-muted';

/** Today in the user's time zone, as YYYY-MM-DD (a record is never in the future). */
export function localToday(now: Date = new Date()): string {
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

const EMPTY: RecordForm = { parcelId: '', cropId: '', date: '', variety: '', seedingRate: '', sowingMethod: '', harvestedWeight: '' };

export interface RecordFormViewProps {
  kind: RecordKind;
  loading: boolean;
  loadError: boolean;
  targets: RecordTarget[];
  names: Record<string, string>;
  form: RecordForm;
  today: string;
  saving: boolean;
  error: string | null;
  onChange: (form: RecordForm) => void;
  onSubmit: () => void;
  onClose: () => void;
  onRetry: () => void;
}

export function targetLabel(t: (k: string, o?: Record<string, unknown>) => string, target: RecordTarget,
  names: Record<string, string>): string {
  const crop = (target.species && names[target.species]) || target.species || '—';
  const role = target.role && target.role !== 'main_crop' ? ` (${t(`record.role.${target.role}`)})` : '';
  const campaign = target.campaign != null ? ` · ${t('record.campaign', { campaign: target.campaign })}` : '';
  return `${target.parcelName} — ${crop}${role}${campaign}`;
}

/** The record form, without data fetching (rendered by the container below and by tests). */
export function RecordFormView(p: RecordFormViewProps) {
  const { t } = useTranslation('field-operations');
  const sowing = p.kind === 'sowing';
  const chosen = p.targets.find((x) => x.cropId === p.form.cropId) ?? null;
  const pick = (cropId: string) => {
    const target = p.targets.find((x) => x.cropId === cropId);
    p.onChange({ ...p.form, cropId, parcelId: target?.parcelId ?? '', variety: target?.variety ?? p.form.variety });
  };
  const set = (field: keyof RecordForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    p.onChange({ ...p.form, [field]: e.target.value });

  let body: React.ReactNode;
  if (p.loading) {
    body = <p className="text-sm text-nkz-text-muted">{t('record.loading')}</p>;
  } else if (p.loadError) {
    body = (
      <div className="text-sm text-nkz-text-muted">
        <p>{t('record.loadError')}</p>
        <button type="button" onClick={p.onRetry} className="mt-2 text-xs text-nkz-accent-base hover:underline">{t('retry')}</button>
      </div>
    );
  } else if (p.targets.length === 0) {
    body = <p className="text-sm text-nkz-text-muted">{t(sowing ? 'record.noTargetsSowing' : 'record.noTargetsHarvest')}</p>;
  } else {
    body = (
      <div className="space-y-3">
        <label className="block">
          <span className={LABEL}>{t('record.crop')}</span>
          <select id="record-crop" value={p.form.cropId} onChange={(e) => pick(e.target.value)} className={INPUT}>
            <option value="">—</option>
            {p.targets.map((x) => <option key={x.cropId} value={x.cropId}>{targetLabel(t, x, p.names)}</option>)}
          </select>
          {chosen?.plannedStart && sowing && (
            <span className="text-xs text-nkz-text-muted">{t('record.planned', { date: chosen.plannedStart })}</span>
          )}
        </label>
        <label className="block">
          <span className={LABEL}>{t('record.date')}</span>
          <input id="record-date" type="date" max={p.today} value={p.form.date} onChange={set('date')} className={INPUT} />
        </label>
        {sowing ? (
          <>
            <label className="block">
              <span className={LABEL}>{t('record.variety')}</span>
              <input id="record-variety" type="text" value={p.form.variety} onChange={set('variety')} className={INPUT} />
            </label>
            <label className="block">
              <span className={LABEL}>{t('record.seedingRate')}</span>
              <input id="record-seeding-rate" type="text" inputMode="decimal" value={p.form.seedingRate}
                onChange={set('seedingRate')} className={INPUT} />
            </label>
            <label className="block">
              <span className={LABEL}>{t('fields.sowingMethod')}</span>
              <select id="record-sowing-method" value={p.form.sowingMethod} onChange={set('sowingMethod')} className={INPUT}>
                <option value="">{t('record.noMethod')}</option>
                <option value="direct">{t('fields.directSowing')}</option>
                <option value="conventional">{t('fields.conventionalSowing')}</option>
              </select>
            </label>
          </>
        ) : (
          <label className="block">
            <span className={LABEL}>{t('record.harvestedWeight')}</span>
            <input id="record-harvested-weight" type="text" inputMode="decimal" value={p.form.harvestedWeight}
              onChange={set('harvestedWeight')} className={INPUT} />
          </label>
        )}
        {p.error && <p role="alert" className="text-sm text-nkz-danger">{p.error}</p>}
      </div>
    );
  }
  const canSubmit = !p.loading && !p.loadError && !p.saving && p.targets.length > 0 && Boolean(p.form.cropId && p.form.date);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={p.onClose}>
      <div className="relative bg-nkz-surface rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-nkz-border">
          <h2 className="text-nkz-text-primary font-bold text-base">{t(sowing ? 'record.titleSowing' : 'record.titleHarvest')}</h2>
          <button type="button" onClick={p.onClose} className="text-nkz-text-muted hover:text-nkz-text-primary text-xl leading-none"
            aria-label={t('close')}>×</button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{body}</div>
        <div className="flex justify-end gap-2 p-4 border-t border-nkz-border">
          <button type="button" onClick={p.onClose} className="text-sm text-nkz-text-muted hover:text-nkz-text-primary px-3 py-1.5">
            {t('cancel')}
          </button>
          <button id="record-submit" type="button" onClick={p.onSubmit} disabled={!canSubmit}
            className="text-sm font-medium rounded-md px-3 py-1.5 bg-nkz-accent-base text-white disabled:opacity-50">
            {p.saving ? t('record.saving') : t('record.submit')}
          </button>
        </div>
      </div>
    </div>
  );
}

interface Props {
  kind: RecordKind;
  onClose: () => void;
  onRecorded: (message: string) => void;
}

const RecordOperationModal: React.FC<Props> = ({ kind, onClose, onRecorded }) => {
  const { t, i18n } = useTranslation('field-operations');
  const [targets, setTargets] = useState<RecordTarget[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [form, setForm] = useState<RecordForm>({ ...EMPTY, date: localToday() });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const resp = await fetch(`${API_BASE}/parcels`, { credentials: 'include' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = (await resp.json()) as { parcels: ParcelView[] };
      setTargets(targetsFor(data.parcels ?? [], kind));
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
    // Names only: the list works with crop codes when planning cannot be reached.
    try {
      const resp = await fetch(`${API_ORIGIN}/api/graph/planning/farm`, { credentials: 'include' });
      if (resp.ok) setNames(cropNamesFromFarm(await resp.json(), i18n?.language?.slice(0, 2) || 'es'));
    } catch { /* names stay as codes */ }
  }, [kind, i18n]);

  useEffect(() => { void load(); }, [load]);

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      const resp = await fetch(`${API_BASE}/operations/record`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildRecordBody(kind, form)),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.status !== 201) {
        setError(t(errorKey(data?.detail?.code), { detail: data?.detail?.detail ?? '' }));
        return;
      }
      const target = targets.find((x) => x.cropId === data.crop_id);
      onRecorded(t(kind === 'sowing' ? 'record.successSowing' : 'record.successHarvest', {
        crop: target ? targetLabel(t, target, names) : (data.species ?? ''),
      }));
    } catch {
      setError(t('record.error.generic'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <RecordFormView kind={kind} loading={loading} loadError={loadError} targets={targets} names={names}
      form={form} today={localToday()} saving={saving} error={error} onChange={setForm}
      onSubmit={() => void submit()} onClose={onClose} onRetry={() => void load()} />
  );
};

export default RecordOperationModal;
