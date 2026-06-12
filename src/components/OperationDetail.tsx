import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import PhotoUpload from './PhotoUpload';
import type { Operation } from './OperationCard';

interface OperationDetailProps {
  operation: Operation;
  onClose: () => void;
  onSaved: () => void;
}

const API_BASE = '/api/field-operations';

// ─── Field form rendered per operationType ────────────────────────────────────
interface FormFieldsProps {
  operationType: string;
  form: Record<string, unknown>;
  onChange: (f: Record<string, unknown>) => void;
  t: (key: string) => string;
}

function FieldInput({
  label, field, type = 'text', form, onChange, t,
}: {
  label: string;
  field: string;
  type?: string;
  form: Record<string, unknown>;
  onChange: (f: Record<string, unknown>) => void;
  t: (k: string) => string;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-nkz-text-muted">{label}</span>
      <input
        type={type}
        value={(form[field] as string | number) ?? ''}
        onChange={e => onChange({ ...form, [field]: type === 'number' ? Number(e.target.value) : e.target.value })}
        className="mt-0.5 block w-full rounded-md border border-nkz-border bg-nkz-background px-2 py-1.5 text-sm text-nkz-text-primary focus:outline-none focus:ring-1 focus:ring-nkz-accent-base"
      />
    </label>
  );
}

function FieldSelect({
  label, field, options, form, onChange,
}: {
  label: string;
  field: string;
  options: { value: string; label: string }[];
  form: Record<string, unknown>;
  onChange: (f: Record<string, unknown>) => void;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-nkz-text-muted">{label}</span>
      <select
        value={(form[field] as string) ?? ''}
        onChange={e => onChange({ ...form, [field]: e.target.value })}
        className="mt-0.5 block w-full rounded-md border border-nkz-border bg-nkz-background px-2 py-1.5 text-sm text-nkz-text-primary focus:outline-none focus:ring-1 focus:ring-nkz-accent-base"
      >
        <option value="">—</option>
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}

function FormFields({ operationType, form, onChange, t }: FormFieldsProps) {
  switch (operationType) {
    case 'sowing':
      return (
        <div className="grid grid-cols-1 gap-3">
          <FieldInput label={t('fields.cropType')}    field="cropType"    form={form} onChange={onChange} t={t} />
          <FieldInput label={t('fields.variety')}     field="variety"     form={form} onChange={onChange} t={t} />
          <FieldInput label={t('fields.seedingRate')} field="seedingRate" type="number" form={form} onChange={onChange} t={t} />
          <FieldSelect
            label={t('fields.irrigationRegime')}
            field="irrigationRegime"
            form={form}
            onChange={onChange}
            options={[
              { value: 'irrigated', label: t('fields.irrigated') },
              { value: 'rainfed',   label: t('fields.rainfed') },
            ]}
          />
        </div>
      );
    case 'irrigation':
      return (
        <div className="grid grid-cols-1 gap-3">
          <FieldInput label={t('fields.waterVolume')}     field="waterVolume"     type="number" form={form} onChange={onChange} t={t} />
          <FieldInput label={t('fields.waterPerHectare')} field="waterPerHectare" type="number" form={form} onChange={onChange} t={t} />
        </div>
      );
    case 'fertilization':
      return (
        <div className="grid grid-cols-1 gap-3">
          <FieldInput label={t('fields.fertilizerType')}        field="fertilizerType"        form={form} onChange={onChange} t={t} />
          <FieldInput label={t('fields.fertilizerRate')}        field="fertilizerRate"        type="number" form={form} onChange={onChange} t={t} />
          <FieldInput label={t('fields.fertilizerComposition')} field="fertilizerComposition" form={form} onChange={onChange} t={t} />
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={(form['organicFertilizer'] as boolean) ?? false}
              onChange={e => onChange({ ...form, organicFertilizer: e.target.checked })}
              className="rounded border-nkz-border"
            />
            <span className="text-sm text-nkz-text-primary">{t('fields.organicFertilizer')}</span>
          </label>
        </div>
      );
    case 'spraying':
      return (
        <div className="grid grid-cols-1 gap-3">
          <FieldInput label={t('fields.productName')}        field="productName"        form={form} onChange={onChange} t={t} />
          <FieldInput label={t('fields.productRate')}        field="productRate"        type="number" form={form} onChange={onChange} t={t} />
          <FieldInput label={t('fields.productRegistryRef')} field="productRegistryRef" form={form} onChange={onChange} t={t} />
          <FieldSelect
            label={t('fields.applicationMethod')}
            field="applicationMethod"
            form={form}
            onChange={onChange}
            options={[
              { value: 'foliar', label: t('fields.foliar') },
              { value: 'soil',   label: t('fields.soil') },
              { value: 'drip',   label: t('fields.drip') },
            ]}
          />
        </div>
      );
    case 'tillage':
      return (
        <div className="grid grid-cols-1 gap-3">
          <FieldSelect
            label={t('fields.tillageType')}
            field="tillageType"
            form={form}
            onChange={onChange}
            options={[
              { value: 'ploughing', label: t('fields.ploughing') },
              { value: 'harrowing', label: t('fields.harrowing') },
              { value: 'cultivating', label: t('fields.cultivating') },
              { value: 'rolling', label: t('fields.rolling') },
              { value: 'subsoiling', label: t('fields.subsoiling') },
              { value: 'roller_crimper', label: t('fields.rollerCrimper') },
            ]}
          />
          <FieldInput label={t('fields.tillageDepth')} field="tillageDepth" type="number" form={form} onChange={onChange} t={t} />
        </div>
      );
    case 'harvesting':
      return (
        <div className="grid grid-cols-1 gap-3">
          <FieldInput label={t('fields.harvestedWeight')} field="harvestedWeight" type="number" form={form} onChange={onChange} t={t} />
          <FieldInput label={t('fields.moisture')} field="moisture" type="number" form={form} onChange={onChange} t={t} />
          <FieldSelect
            label={t('fields.harvestDestination')}
            field="harvestDestination"
            form={form}
            onChange={onChange}
            options={[
              { value: 'storage', label: t('fields.storage') },
              { value: 'sale', label: t('fields.sale') },
              { value: 'feed', label: t('fields.feed') },
            ]}
          />
        </div>
      );
    case 'haymaking':
      return (
        <div className="grid grid-cols-1 gap-3">
          <FieldInput label={t('fields.cropType')} field="cropType" form={form} onChange={onChange} t={t} />
          <FieldSelect
            label={t('fields.swathType')}
            field="swathType"
            form={form}
            onChange={onChange}
            options={[
              { value: 'tedding', label: t('fields.tedding') },
              { value: 'raking', label: t('fields.raking') },
              { value: 'mowing', label: t('fields.mowing') },
            ]}
          />
          <FieldInput label={t('fields.moisture')} field="moisture" type="number" form={form} onChange={onChange} t={t} />
        </div>
      );
    case 'baling':
      return (
        <div className="grid grid-cols-1 gap-3">
          <FieldInput label={t('fields.cropType')} field="cropType" form={form} onChange={onChange} t={t} />
          <FieldSelect
            label={t('fields.baleType')}
            field="baleType"
            form={form}
            onChange={onChange}
            options={[
              { value: 'round', label: t('fields.round') },
              { value: 'square', label: t('fields.square') },
            ]}
          />
          <FieldInput label={t('fields.baleCount')} field="baleCount" type="number" form={form} onChange={onChange} t={t} />
          <FieldInput label={t('fields.baleWeight')} field="baleWeight" type="number" form={form} onChange={onChange} t={t} />
        </div>
      );
    case 'scouting':
      return (
        <div className="grid grid-cols-1 gap-3">
          <FieldSelect
            label={t('fields.platformType')}
            field="platformType"
            form={form}
            onChange={onChange}
            options={[
              { value: 'drone', label: t('fields.drone') },
              { value: 'rover', label: t('fields.rover') },
              { value: 'satellite', label: t('fields.satellite') },
              { value: 'manual', label: t('fields.manualInspection') },
            ]}
          />
          <FieldInput label={t('fields.sensorType')} field="sensorType" form={form} onChange={onChange} t={t} />
          <FieldInput label={t('fields.coveragePct')} field="coveragePct" type="number" form={form} onChange={onChange} t={t} />
          <FieldInput label={t('fields.notes')} field="notes" form={form} onChange={onChange} t={t} />
        </div>
      );
    default:
      return <p className="text-nkz-text-muted text-sm">{t('fields.noSpecificFields')}</p>;
  }
}

// ─── Extrapolation preview ────────────────────────────────────────────────────
interface ExtrapolatePreviewProps {
  areaCovered: number;
  parcelAreaHa: number;
  setParcelAreaHa: (v: number) => void;
  onConfirm: () => void;
  saving: boolean;
  t: (k: string) => string;
}

function ExtrapolatePreview({
  areaCovered, parcelAreaHa, setParcelAreaHa, onConfirm, saving, t,
}: ExtrapolatePreviewProps) {
  const factor = parcelAreaHa > 0 ? parcelAreaHa / areaCovered : 0;

  return (
    <div className="mt-2 p-3 bg-blue-50 rounded-lg border border-blue-200">
      <p className="text-xs font-semibold text-blue-700 mb-2">{t('extrapolate.preview')}</p>
      <label className="block text-xs text-nkz-text-muted">
        {t('extrapolate.parcelAreaHa')}
        <input
          type="number"
          min={areaCovered}
          step={0.1}
          value={parcelAreaHa || ''}
          onChange={e => setParcelAreaHa(Number(e.target.value))}
          className="mt-0.5 block w-full rounded border border-blue-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
      </label>
      {parcelAreaHa > 0 && (
        <p className="mt-2 text-xs text-blue-700 font-mono bg-white p-2 rounded border border-blue-100">
          ({areaCovered} Ha {t('extrapolate.registered')} / {parcelAreaHa} Ha {t('extrapolate.total')}) × {t('extrapolate.values')}
          {' = '}
          <strong>×{factor.toFixed(3)}</strong>
        </p>
      )}
      <button
        id="extrapolate-confirm"
        onClick={onConfirm}
        disabled={!parcelAreaHa || parcelAreaHa <= areaCovered || saving}
        className="mt-2 w-full text-xs bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold py-1.5 rounded transition-colors"
      >
        {saving ? t('saving') : t('extrapolate.confirm')}
      </button>
    </div>
  );
}

// ─── Main OperationDetail modal ───────────────────────────────────────────────
const OperationDetail: React.FC<OperationDetailProps> = ({ operation, onClose, onSaved }) => {
  const { t } = useTranslation('field-operations');

  const [form, setForm]                         = useState<Record<string, unknown>>({});
  const [parcelAreaHa, setParcelAreaHa]         = useState<number>(0);
  const [showExtrapolate, setShowExtrapolate]   = useState(false);
  const [saving, setSaving]                     = useState(false);
  const [siexSaving, setSiexSaving]             = useState(false);
  const [actionError, setActionError]           = useState<string | null>(null);

  const status    = operation.status?.value ?? '';
  const opType    = operation.operationType?.value ?? '';
  const dataSource = operation.dataSource?.value ?? 'manual';

  const hasIsobus     = dataSource === 'isobus' || dataSource === 'mixed';
  const areaCovered   = operation.areaCovered?.value ?? null;
  const hasMachineData = hasIsobus && (
    operation.fuelUsed?.value != null ||
    operation.engineHours?.value != null ||
    areaCovered != null
  );

  const canExtrapolate = areaCovered != null && status === 'incomplete';
  const canSiex        = ['spraying', 'fertilization'].includes(opType) && status === 'completed';
  const canEdit        = status === 'incomplete' || status === 'needs_review';

  async function handleComplete() {
    setSaving(true);
    setActionError(null);
    try {
      const resp = await fetch(
        `${API_BASE}/operations/${encodeURIComponent(operation.id)}/complete`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(form),
        }
      );
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail ?? `HTTP ${resp.status}`);
      }
      onSaved();
      onClose();
    } catch (e) {
      setActionError(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleExtrapolate() {
    setSaving(true);
    setActionError(null);
    try {
      const resp = await fetch(
        `${API_BASE}/operations/${encodeURIComponent(operation.id)}/extrapolate`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ parcel_area_ha: parcelAreaHa }),
        }
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      onSaved();
      onClose();
    } catch (e) {
      setActionError(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleSiex() {
    setSiexSaving(true);
    setActionError(null);
    try {
      const resp = await fetch(
        `${API_BASE}/operations/${encodeURIComponent(operation.id)}/registrar-siex`,
        { method: 'POST', credentials: 'include' }
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      onSaved();
    } catch (e) {
      setActionError(String(e));
    } finally {
      setSiexSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
      id="operation-detail-overlay"
    >
      <div
        className="relative bg-nkz-surface rounded-xl shadow-2xl w-full max-w-3xl mx-4 max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-nkz-border">
          <div>
            <h2 className="text-nkz-text-primary font-bold text-base">
              {t(`operationTypes.${opType}`)}
            </h2>
            <p className="text-xs text-nkz-text-muted mt-0.5">
              {operation.workOrder?.value ?? '—'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
              status === 'needs_review' ? 'bg-red-100 text-red-700' :
              status === 'incomplete'   ? 'bg-orange-100 text-orange-700' :
              status === 'planned'      ? 'bg-blue-100 text-blue-700' :
              status === 'completed'    ? 'bg-green-100 text-green-700' :
              'bg-nkz-surface text-nkz-text-muted'
            }`}>
              {t(`statuses.${status}`)}
            </span>
            <button
              id="operation-detail-close"
              onClick={onClose}
              className="text-nkz-text-muted hover:text-nkz-text-primary text-xl leading-none"
              aria-label={t('close')}
            >
              ×
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          <div className={`p-4 ${hasMachineData || hasIsobus ? 'grid grid-cols-2 gap-4' : ''}`}>

            {/* LEFT: Machine data (ISOBUS, read-only) */}
            {(hasMachineData || hasIsobus) && (
              <div className="border-r border-nkz-border pr-4">
                <h3 className="text-xs font-semibold text-nkz-text-muted uppercase tracking-wide mb-3">
                  📡 {t('machineData.title')}
                </h3>
                {hasMachineData ? (
                  <dl className="space-y-2">
                    {operation.fuelUsed?.value != null && (
                      <div>
                        <dt className="text-xs text-nkz-text-muted">{t('machineData.fuelUsed')}</dt>
                        <dd className="text-sm font-semibold text-nkz-text-primary">
                          {operation.fuelUsed.value} L
                        </dd>
                      </div>
                    )}
                    {operation.engineHours?.value != null && (
                      <div>
                        <dt className="text-xs text-nkz-text-muted">{t('machineData.engineHours')}</dt>
                        <dd className="text-sm font-semibold text-nkz-text-primary">
                          {operation.engineHours.value} h
                        </dd>
                      </div>
                    )}
                    {areaCovered != null && (
                      <div>
                        <dt className="text-xs text-nkz-text-muted">{t('machineData.areaCovered')}</dt>
                        <dd className="text-sm font-semibold text-nkz-text-primary">
                          {areaCovered} Ha
                        </dd>
                      </div>
                    )}
                  </dl>
                ) : (
                  <p className="text-sm text-nkz-text-muted italic">
                    {t('machineData.noData')}
                  </p>
                )}

                {/* Extrapolate section */}
                {canExtrapolate && (
                  <div className="mt-4">
                    <button
                      id="extrapolate-toggle"
                      onClick={() => setShowExtrapolate(v => !v)}
                      className="text-xs text-blue-600 hover:underline font-medium"
                    >
                      📐 {t('extrapolate.trigger')}
                    </button>
                    {showExtrapolate && (
                      <ExtrapolatePreview
                        areaCovered={areaCovered!}
                        parcelAreaHa={parcelAreaHa}
                        setParcelAreaHa={setParcelAreaHa}
                        onConfirm={handleExtrapolate}
                        saving={saving}
                        t={t}
                      />
                    )}
                  </div>
                )}
              </div>
            )}

            {/* RIGHT: Human form */}
            <div className={hasMachineData || hasIsobus ? '' : 'col-span-2'}>
              <h3 className="text-xs font-semibold text-nkz-text-muted uppercase tracking-wide mb-3">
                ✏️ {t('form.title')}
              </h3>

              {canEdit ? (
                <FormFields
                  operationType={opType}
                  form={form}
                  onChange={setForm}
                  t={t}
                />
              ) : (
                <p className="text-sm text-nkz-text-muted italic">
                  {t('form.readOnly')}
                </p>
              )}

              {/* Photo upload (all editable operations) */}
              {canEdit && (
                <PhotoUpload
                  operationId={operation.id}
                  currentUrl={(operation['labelPhoto'] as { value?: { url?: string } } | undefined)?.value?.url}
                />
              )}

              {/* SIEX button */}
              {canSiex && (
                <div className="mt-4">
                  <button
                    id="siex-register-btn"
                    onClick={handleSiex}
                    disabled={siexSaving}
                    className="w-full text-sm bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white font-semibold py-2 rounded-lg transition-colors"
                  >
                    {siexSaving ? t('saving') : `📋 ${t('siex.register')}`}
                  </button>
                </div>
              )}
            </div>
          </div>

          {actionError && (
            <div className="mx-4 mb-4 p-2 bg-red-50 rounded-lg text-xs text-red-600 border border-red-200">
              {actionError}
            </div>
          )}
        </div>

        {/* Footer */}
        {canEdit && (
          <div className="flex items-center justify-end gap-2 p-4 border-t border-nkz-border">
            <button
              onClick={onClose}
              className="text-sm px-4 py-2 rounded-lg border border-nkz-border text-nkz-text-muted hover:bg-nkz-background transition-colors"
            >
              {t('cancel')}
            </button>
            <button
              id="operation-complete-btn"
              onClick={handleComplete}
              disabled={saving}
              className="text-sm px-4 py-2 rounded-lg bg-nkz-accent-base hover:bg-nkz-accent-dark disabled:opacity-50 text-white font-semibold transition-colors"
            >
              {saving ? t('saving') : t('form.complete')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default OperationDetail;
