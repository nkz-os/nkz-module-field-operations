import { useEffect, useState } from 'react';

const API_BASE = '/api/field-operations';
const DEBOUNCE_MS = 400;

export type PesticideValidationStatus =
  | 'idle'
  | 'loading'
  | 'authorized'
  | 'not_authorized'
  | 'unknown_substance'
  | 'skipped';

export interface PesticideValidationState {
  status: PesticideValidationStatus;
  detail: string;
  cropEppo?: string;
}

export function usePesticideValidation(
  parcelId: string | undefined,
  productName: string,
): PesticideValidationState {
  const [state, setState] = useState<PesticideValidationState>({
    status: 'idle',
    detail: '',
  });

  useEffect(() => {
    const trimmed = productName.trim();
    if (!parcelId || !trimmed) {
      setState({ status: 'idle', detail: '' });
      return;
    }

    let cancelled = false;
    setState(prev => ({ ...prev, status: 'loading' }));

    const timer = window.setTimeout(async () => {
      try {
        const params = new URLSearchParams({
          parcel_id: parcelId,
          product_name: trimmed,
        });
        const resp = await fetch(
          `${API_BASE}/validate-pesticide?${params.toString()}`,
          { credentials: 'include' },
        );
        if (!resp.ok) {
          if (!cancelled) {
            setState({ status: 'unknown_substance', detail: `HTTP ${resp.status}` });
          }
          return;
        }
        const data = await resp.json();
        if (cancelled) return;

        const apiStatus = data.status as string;
        let uiStatus: PesticideValidationStatus = 'unknown_substance';
        if (apiStatus === 'authorized') uiStatus = 'authorized';
        else if (apiStatus === 'not_authorized') uiStatus = 'not_authorized';
        else if (apiStatus === 'skipped') uiStatus = 'skipped';
        else if (apiStatus === 'unknown_substance') uiStatus = 'unknown_substance';

        setState({
          status: uiStatus,
          detail: data.detail ?? '',
          cropEppo: data.crop_eppo,
        });
      } catch (e) {
        if (!cancelled) {
          setState({ status: 'unknown_substance', detail: String(e) });
        }
      }
    }, DEBOUNCE_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [parcelId, productName]);

  return state;
}
