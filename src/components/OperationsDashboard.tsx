import { API_ORIGIN } from '../lib/apiOrigin';
import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';
import OperationCard, { Operation } from './OperationCard';
import OperationsTable from './OperationsTable';
import { normalizeOperation } from '../lib/normalizeOperation';
import RecordOperationModal from './RecordOperationModal';
import type { RecordKind } from '../lib/recordModel';

interface Tab {
  key: string;
  statusFilter: string[];
  labelKey: string;
}

const TABS: Tab[] = [
  { key: 'pending',   statusFilter: ['needs_review', 'incomplete'], labelKey: 'tabs.pending' },
  { key: 'planned',   statusFilter: ['planned'],                    labelKey: 'tabs.planned' },
  { key: 'history',   statusFilter: ['completed'],                  labelKey: 'tabs.history' },
  { key: 'cancelled', statusFilter: ['cancelled'],                  labelKey: 'tabs.cancelled' },
];

interface OperationsDashboardProps {
  parcelId?: string;
  onSelectOperation: (op: Operation) => void;
}

const API_BASE = `${API_ORIGIN}/api/field-operations`;

const OperationsDashboard: React.FC<OperationsDashboardProps> = ({ parcelId, onSelectOperation }) => {
  const { t } = useTranslation('field-operations');
  const [operations, setOperations] = useState<Operation[]>([]);
  const [activeTab, setActiveTab]   = useState<string>('pending');
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState<string | null>(null);
  const [viewMode, setViewMode]     = useState<'cards' | 'table'>('cards');
  const [recording, setRecording]   = useState<RecordKind | null>(null);
  const [notice, setNotice]         = useState<string | null>(null);

  const fetchOperations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: '200' });
      if (parcelId) params.set('parcel_id', parcelId);

      const resp = await fetch(`${API_BASE}/operations?${params}`, { credentials: 'include' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setOperations((data.operations ?? []).map(normalizeOperation));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [parcelId]);

  useEffect(() => { fetchOperations(); }, [fetchOperations]);

  const activeConfig = TABS.find(t => t.key === activeTab)!;
  const filtered = operations.filter(op =>
    activeConfig.statusFilter.includes(op.status?.value ?? '')
  );

  const needsReviewCount = operations.filter(op => op.status?.value === 'needs_review').length;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-nkz-border">
        <h2 className="text-nkz-text-primary font-bold text-sm">🌾 {t('title')}</h2>
        <div className="flex items-center gap-2 ml-auto mr-3">
          <button
            id="field-ops-record-sowing"
            onClick={() => { setNotice(null); setRecording('sowing'); }}
            className="text-xs font-medium rounded-md px-2 py-1 bg-nkz-accent-base text-white"
          >
            {t('record.sow')}
          </button>
          <button
            id="field-ops-record-harvest"
            onClick={() => { setNotice(null); setRecording('harvesting'); }}
            className="text-xs font-medium rounded-md px-2 py-1 border border-nkz-accent-base text-nkz-accent-base"
          >
            {t('record.harvest')}
          </button>
        </div>
        <button
          id="field-ops-refresh"
          onClick={fetchOperations}
          className="text-xs text-nkz-accent-base hover:underline"
          disabled={loading}
        >
          {t('refresh')}
        </button>
        <button
          onClick={() => setViewMode(v => v === 'cards' ? 'table' : 'cards')}
          className="text-xs text-nkz-text-muted hover:text-nkz-accent-base ml-2"
          title={viewMode === 'cards' ? t('tableView') : t('cardView')}
        >
          {viewMode === 'cards' ? '📊' : '📇'}
        </button>
      </div>

      {notice && (
        <div role="status" className="mx-2 mt-2 rounded-md border border-nkz-border bg-nkz-surface px-3 py-2 text-xs text-nkz-text-primary">
          {notice}
        </div>
      )}
      {recording && (
        <RecordOperationModal
          kind={recording}
          onClose={() => setRecording(null)}
          onRecorded={(message) => { setRecording(null); setNotice(message); void fetchOperations(); }}
        />
      )}

      {/* Tabs */}
      <div className="flex border-b border-nkz-border overflow-x-auto flex-shrink-0">
        {TABS.map(tab => (
          <button
            key={tab.key}
            id={`field-ops-tab-${tab.key}`}
            onClick={() => setActiveTab(tab.key)}
            className={`
              relative flex items-center gap-1.5 px-3 py-2 text-xs font-medium whitespace-nowrap transition-colors
              ${activeTab === tab.key
                ? 'text-nkz-accent-base border-b-2 border-nkz-accent-base'
                : 'text-nkz-text-muted hover:text-nkz-text-primary'}
            `}
          >
            {t(tab.labelKey)}
            {tab.key === 'pending' && needsReviewCount > 0 && (
              <span className="inline-flex items-center justify-center w-4 h-4 text-[10px] font-bold text-white bg-nkz-danger rounded-full">
                {needsReviewCount > 9 ? '9+' : needsReviewCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3">
        {loading ? (
          <div className="flex items-center justify-center h-24 text-nkz-text-muted text-sm">
            <span className="animate-pulse">{t('loading')}</span>
          </div>
        ) : error ? (
          <div className="text-nkz-danger text-sm p-3 bg-nkz-danger-soft rounded-lg">
            <p className="font-semibold">{t('errorLoading')}</p>
            <p className="text-xs mt-1">{error}</p>
            <button onClick={fetchOperations} className="mt-2 text-xs text-nkz-danger-strong underline">
              {t('retry')}
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-24 text-nkz-text-muted text-sm gap-1">
            <span className="text-2xl">📋</span>
            <p>{t('noOperations')}</p>
          </div>
        ) : viewMode === 'table' ? (
          <OperationsTable
            operations={filtered}
            onSelectOperation={onSelectOperation}
          />
        ) : (
          <div className="flex flex-col gap-2">
            {filtered.map(op => (
              <OperationCard
                key={op.id}
                operation={op}
                onClick={() => onSelectOperation(op)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default OperationsDashboard;
