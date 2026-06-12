import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import type { Operation } from './OperationCard';

interface OperationsTableProps {
  operations: Operation[];
  onSelectOperation: (op: Operation) => void;
}

const OP_ICON: Record<string, string> = {
  sowing: '🌱', irrigation: '💧', fertilization: '🧪',
  spraying: '🌫️', tillage: '⚙️', harvesting: '🌾',
  haymaking: '🌿', baling: '🧱', scouting: '🔍',
};
const STATUS_COLOR: Record<string, string> = {
  needs_review: 'text-red-600', incomplete: 'text-orange-500',
  planned: 'text-blue-500', issued: 'text-purple-500',
  completed: 'text-green-500', cancelled: 'text-gray-400',
};
const SOURCE_BADGE: Record<string, string> = {
  odoo: 'bg-purple-100 text-purple-700',
  api: 'bg-blue-100 text-blue-700',
  manual: 'bg-gray-100 text-gray-600',
  isobus: 'bg-green-100 text-green-700',
};

function formatDate(val: unknown): string {
  if (!val) return '—';
  const iso = typeof val === 'string' ? val : (val as any)?.['@value'];
  if (!iso) return '—';
  try { return new Date(iso).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' }); }
  catch { return String(iso).slice(0, 10); }
}

const OperationsTable: React.FC<OperationsTableProps> = ({ operations, onSelectOperation }) => {
  const { t } = useTranslation('field-operations');

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-nkz-border text-nkz-text-muted uppercase tracking-wide">
            <th className="text-left py-2 px-2 font-medium">{t('table.date')}</th>
            <th className="text-left py-2 px-2 font-medium">{t('table.type')}</th>
            <th className="text-left py-2 px-2 font-medium">{t('table.workOrder')}</th>
            <th className="text-left py-2 px-2 font-medium">{t('table.product')}</th>
            <th className="text-left py-2 px-2 font-medium">{t('table.dose')}</th>
            <th className="text-left py-2 px-2 font-medium">{t('table.operator')}</th>
            <th className="text-left py-2 px-2 font-medium">{t('table.source')}</th>
            <th className="text-left py-2 px-2 font-medium">{t('table.status')}</th>
          </tr>
        </thead>
        <tbody>
          {operations.map(op => {
            const opType = op.operationType?.value ?? '';
            const productName = (op as any).productName?.value || (op as any).fertilizerType?.value || '—';
            const dose = (op as any).productRate?.value || (op as any).fertilizerRate?.value || '—';
            const source = (op as any).source?.value || op.dataSource?.value || 'manual';
            const dateVal = op.startedAt?.value ?? (op as any).plannedDate?.value;
            const date = formatDate(dateVal);
            const status = op.status?.value ?? '';

            return (
              <tr
                key={op.id}
                onClick={() => onSelectOperation(op)}
                className="border-b border-nkz-border hover:bg-nkz-surface/50 cursor-pointer transition-colors"
              >
                <td className="py-2 px-2 whitespace-nowrap">{date}</td>
                <td className="py-2 px-2">
                  <span className="flex items-center gap-1">
                    {OP_ICON[opType] ?? '📋'}
                    <span>{t(`operationTypes.${opType}`)}</span>
                  </span>
                </td>
                <td className="py-2 px-2 font-mono text-[10px]">{op.workOrder?.value ?? '—'}</td>
                <td className="py-2 px-2">{productName}</td>
                <td className="py-2 px-2">{dose}</td>
                <td className="py-2 px-2">{op.operator?.value ?? '—'}</td>
                <td className="py-2 px-2">
                  <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${SOURCE_BADGE[source] ?? ''}`}>
                    {source}
                  </span>
                </td>
                <td className={`py-2 px-2 font-medium ${STATUS_COLOR[status] ?? ''}`}>
                  {t(`statuses.${status}`)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

export default OperationsTable;
