import React from 'react';
import type { PesticideValidationState } from '../hooks/usePesticideValidation';

interface PesticideValidationBadgeProps {
  validation: PesticideValidationState;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

const BADGE_CLASS: Record<string, string> = {
  loading: 'bg-nkz-surface-sunken text-nkz-text-muted',
  authorized: 'bg-nkz-positive-soft text-nkz-positive',
  not_authorized: 'bg-nkz-negative-soft text-nkz-negative',
  unknown_substance: 'bg-nkz-warning-soft text-nkz-warning',
  skipped: 'bg-nkz-surface-sunken text-nkz-text-muted',
};

const PesticideValidationBadge: React.FC<PesticideValidationBadgeProps> = ({ validation, t }) => {
  const { status, detail, cropEppo } = validation;
  if (status === 'idle') return null;

  const labelKey =
    status === 'loading' ? 'spraying.pesticideChecking' :
    status === 'authorized' ? 'spraying.pesticideAuthorized' :
    status === 'not_authorized' ? 'spraying.pesticideRejected' :
    status === 'skipped' ? 'spraying.pesticideSkipped' :
    'spraying.pesticideUnknown';

  const defaults: Record<string, string> = {
    'spraying.pesticideChecking': 'Checking authorization…',
    'spraying.pesticideAuthorized': 'Authorized for this crop',
    'spraying.pesticideRejected': 'Not authorized for this crop',
    'spraying.pesticideSkipped': 'Validation skipped (no crop assigned)',
    'spraying.pesticideUnknown': 'Could not verify — proceed with caution',
  };

  return (
    <div
      className={`mt-1 px-2 py-1 rounded-nkz-md text-nkz-xs ${BADGE_CLASS[status] ?? BADGE_CLASS.unknown_substance}`}
      role="status"
    >
      <span className="font-medium">{t(labelKey, { defaultValue: defaults[labelKey] })}</span>
      {cropEppo && status === 'authorized' && (
        <span className="ml-1 opacity-80">({cropEppo})</span>
      )}
      {detail && status !== 'authorized' && status !== 'loading' && (
        <div className="mt-0.5 opacity-90">{detail}</div>
      )}
    </div>
  );
};

export default PesticideValidationBadge;
