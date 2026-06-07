import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';
import OperationCard, { Operation } from './OperationCard';

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

const API_BASE = '/api/field-operations';

const OperationsDashboard: React.FC<OperationsDashboardProps> = ({ parcelId, onSelectOperation }) => {
  const { t } = useTranslation('field-operations');
  const [operations, setOperations] = useState<Operation[]>([]);
  const [activeTab, setActiveTab]   = useState<string>('pending');
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState<string | null>(null);

  const fetchOperations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: '200' });
      if (parcelId) params.set('parcel_id', parcelId);

      const resp = await fetch(`${API_BASE}/operations?${params}`, { credentials: 'include' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setOperations(data.operations ?? []);
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
        <button
          id="field-ops-refresh"
          onClick={fetchOperations}
          className="text-xs text-nkz-accent-base hover:underline"
          disabled={loading}
        >
          {t('refresh')}
        </button>
      </div>

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
              <span className="inline-flex items-center justify-center w-4 h-4 text-[10px] font-bold text-white bg-red-500 rounded-full">
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
          <div className="text-red-500 text-sm p-3 bg-red-50 rounded-lg">
            <p className="font-semibold">{t('errorLoading')}</p>
            <p className="text-xs mt-1">{error}</p>
            <button onClick={fetchOperations} className="mt-2 text-xs text-red-700 underline">
              {t('retry')}
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-24 text-nkz-text-muted text-sm gap-1">
            <span className="text-2xl">📋</span>
            <p>{t('noOperations')}</p>
          </div>
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
