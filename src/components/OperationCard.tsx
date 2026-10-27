import React from 'react';
import { useTranslation } from '@nekazari/sdk';

export interface Operation {
  id: string;
  operationType?: { value: string };
  status?: { value: string };
  workOrder?: { value: string };
  operator?: { value: string };
  startedAt?: { value: { '@value': string } | string };
  endedAt?: { value: { '@value': string } | string };
  dataSource?: { value: string };
  fuelUsed?: { value: number; unitCode?: string };
  engineHours?: { value: number; unitCode?: string };
  areaCovered?: { value: number; unitCode?: string };
  hasAgriParcel?: { object: string };
  [key: string]: unknown;
}

interface OperationCardProps {
  operation: Operation;
  onClick: () => void;
}

const STATUS_BORDER: Record<string, string> = {
  needs_review: 'border-l-4 border-l-nkz-danger',
  incomplete:   'border-l-4 border-l-nkz-warning',
  planned:      'border-l-4 border-l-nkz-info',
  completed:    'border-l-4 border-l-nkz-success',
  cancelled:    'border-l-4 border-l-nkz-border opacity-60',
};

const STATUS_BADGE: Record<string, string> = {
  needs_review: 'bg-nkz-danger-soft text-nkz-danger-strong',
  incomplete:   'bg-nkz-warning-soft text-nkz-warning-strong',
  planned:      'bg-nkz-info-soft text-nkz-info-strong',
  completed:    'bg-nkz-success-soft text-nkz-success-strong',
  cancelled:    'bg-nkz-surface text-nkz-text-muted',
};

const OP_ICON: Record<string, string> = {
  sowing:        '🌱',
  irrigation:    '💧',
  fertilization: '🧪',
  spraying:      '🌫️',
  tillage:       '⚙️',
  harvesting:    '🌾',
  haymaking:     '🌿',
  baling:        '🧱',
  scouting:      '🔍',
};

function formatDate(val: { '@value': string } | string | undefined): string {
  if (!val) return '—';
  const iso = typeof val === 'string' ? val : val['@value'];
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('es-ES', {
      day: '2-digit', month: 'short', year: 'numeric',
    });
  } catch {
    return iso.slice(0, 10);
  }
}

const OperationCard: React.FC<OperationCardProps> = ({ operation, onClick }) => {
  const { t } = useTranslation('field-operations');

  const status    = operation.status?.value ?? 'unknown';
  const opType    = operation.operationType?.value ?? '';
  const workOrder = operation.workOrder?.value ?? '—';
  const operator  = operation.operator?.value ?? '—';
  const dateVal   = operation.startedAt?.value ?? operation.endedAt?.value;
  const date      = formatDate(dateVal as { '@value': string } | string | undefined);
  const icon      = OP_ICON[opType] ?? '📋';

  return (
    <button
      className={`w-full text-left bg-nkz-surface rounded-lg p-3 shadow-sm hover:shadow-md transition-shadow cursor-pointer ${STATUS_BORDER[status] ?? ''}`}
      onClick={onClick}
      id={`op-card-${operation.id.split(':').pop()}`}
      aria-label={`${t(`operationTypes.${opType}`)} — ${t(`statuses.${status}`)}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-lg flex-shrink-0">{icon}</span>
          <div className="min-w-0">
            <p className="text-nkz-text-primary font-semibold text-sm truncate">
              {t(`operationTypes.${opType}`)}
            </p>
            <p className="text-nkz-text-muted text-xs truncate">{workOrder}</p>
          </div>
        </div>
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${STATUS_BADGE[status] ?? 'bg-nkz-surface'}`}>
          {t(`statuses.${status}`)}
        </span>
      </div>

      <div className="flex items-center gap-3 mt-2 text-xs text-nkz-text-muted">
        <span>👤 {operator}</span>
        <span>📅 {date}</span>
        {operation.dataSource?.value === 'isobus' && (
          <span className="text-nkz-info font-medium">ISOBUS</span>
        )}
        {operation.dataSource?.value === 'mixed' && (
          <span className="text-nkz-accent-strong font-medium">ISOBUS + Manual</span>
        )}
      </div>
    </button>
  );
};

export default OperationCard;
