import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { API_ORIGIN } from '../lib/apiOrigin';
import {
  buildPlantationBody, canDeclare, plantationErrorKey, plantationParcels, type ParcelView, type PlantationForm,
} from '../lib/recordModel';
import { woodyOptions } from '../lib/woodySpecies';
import { localToday } from './RecordOperationModal';

const API_BASE = `${API_ORIGIN}/api/field-operations`;
const INPUT = 'mt-0.5 block w-full rounded-md border border-nkz-border bg-nkz-bg px-2 py-1.5 text-sm text-nkz-text-primary focus:outline-none focus:ring-1 focus:ring-nkz-accent-base';
const LABEL = 'text-xs font-medium text-nkz-text-muted';

const EMPTY: PlantationForm = { parcelId: '', eppo: '', year: '', date: '', variety: '' };

export interface DeclarePlantationViewProps {
  loading: boolean;
  loadError: boolean;
  parcels: { id: string; name: string }[];
  form: PlantationForm;
  lang: string;
  today: string;
  saving: boolean;
  error: string | null;
  onChange: (form: PlantationForm) => void;
  onSubmit: () => void;
  onClose: () => void;
  onRetry: () => void;
}

/** The declare-plantation form, without data fetching (rendered by the container below and by tests). */
export function DeclarePlantationView(p: DeclarePlantationViewProps) {
  const { t } = useTranslation('field-operations');
  const set = (field: keyof PlantationForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
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
  } else if (p.parcels.length === 0) {
    body = <p className="text-sm text-nkz-text-muted">{t('plantation.noParcels')}</p>;
  } else {
    body = (
      <div className="space-y-3">
        <label className="block">
          <span className={LABEL}>{t('plantation.parcel')}</span>
          <select id="plantation-parcel" value={p.form.parcelId} onChange={set('parcelId')} className={INPUT}>
            <option value="">—</option>
            {p.parcels.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </label>
        <label className="block">
          <span className={LABEL}>{t('plantation.species')}</span>
          <select id="plantation-species" value={p.form.eppo} onChange={set('eppo')} className={INPUT}>
            <option value="">—</option>
            {woodyOptions(p.lang).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        <label className="block">
          <span className={LABEL}>{t('plantation.year')}</span>
          <input id="plantation-year" type="text" inputMode="numeric" maxLength={4} value={p.form.year}
            onChange={set('year')} className={INPUT} />
        </label>
        <label className="block">
          <span className={LABEL}>{t('plantation.day')}</span>
          <input id="plantation-date" type="date" max={p.today} value={p.form.date} onChange={set('date')} className={INPUT} />
        </label>
        <label className="block">
          <span className={LABEL}>{t('plantation.variety')}</span>
          <input id="plantation-variety" type="text" value={p.form.variety} onChange={set('variety')} className={INPUT} />
        </label>
        {p.error && <p role="alert" className="text-sm text-nkz-danger">{p.error}</p>}
      </div>
    );
  }
  const ready = !p.loading && !p.loadError && !p.saving && p.parcels.length > 0 && canDeclare(p.form);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={p.onClose}>
      <div className="relative bg-nkz-surface rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-nkz-border">
          <h2 className="text-nkz-text-primary font-bold text-base">{t('plantation.title')}</h2>
          <button type="button" onClick={p.onClose} className="text-nkz-text-muted hover:text-nkz-text-primary text-xl leading-none"
            aria-label={t('close')}>×</button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{body}</div>
        <div className="flex justify-end gap-2 p-4 border-t border-nkz-border">
          <button type="button" onClick={p.onClose} className="text-sm text-nkz-text-muted hover:text-nkz-text-primary px-3 py-1.5">
            {t('cancel')}
          </button>
          <button id="plantation-submit" type="button" onClick={p.onSubmit} disabled={!ready}
            className="text-sm font-medium rounded-md px-3 py-1.5 bg-nkz-accent-base text-white disabled:opacity-50">
            {p.saving ? t('record.saving') : t('plantation.submit')}
          </button>
        </div>
      </div>
    </div>
  );
}

interface Props {
  onClose: () => void;
  onDeclared: (message: string) => void;
}

const DeclarePlantationModal: React.FC<Props> = ({ onClose, onDeclared }) => {
  const { t, i18n } = useTranslation('field-operations');
  const [parcels, setParcels] = useState<{ id: string; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [form, setForm] = useState<PlantationForm>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const resp = await fetch(`${API_BASE}/parcels`, { credentials: 'include' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = (await resp.json()) as { parcels: ParcelView[] };
      setParcels(plantationParcels(data.parcels ?? []));
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      const resp = await fetch(`${API_BASE}/parcels/${encodeURIComponent(form.parcelId)}/plantations`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildPlantationBody(form)),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.status !== 201) {
        setError(t(plantationErrorKey(data?.detail?.code), { detail: data?.detail?.detail ?? '' }));
        return;
      }
      onDeclared(t('plantation.success'));
    } catch {
      setError(t('record.error.generic'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <DeclarePlantationView loading={loading} loadError={loadError} parcels={parcels} form={form}
      lang={i18n?.language?.slice(0, 2) || 'es'} today={localToday()} saving={saving} error={error}
      onChange={setForm} onSubmit={() => void submit()} onClose={onClose} onRetry={() => void load()} />
  );
};

export default DeclarePlantationModal;
