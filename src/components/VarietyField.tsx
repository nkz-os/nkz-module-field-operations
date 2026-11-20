import React, { useState } from 'react';
import { canonicalVariety, isOutsideCatalog, type VarietyEntry } from '../lib/varietyCatalog';

const INPUT = 'mt-0.5 block w-full rounded-md border border-nkz-border bg-nkz-bg px-2 py-1.5 text-sm text-nkz-text-primary focus:outline-none focus:ring-1 focus:ring-nkz-accent-base';
const LABEL = 'text-xs font-medium text-nkz-text-muted';

/** The catalog spelling to set on blur, or null when the field already holds it or is not a catalog variety. */
export function varietyAfterBlur(value: string, entries: VarietyEntry[]): string | null {
  const canonical = canonicalVariety(value, entries);
  return canonical === value ? null : canonical;
}

export interface VarietyFieldProps {
  id: string;
  label: string;
  value: string;
  entries: VarietyEntry[];
  notice: string;
  onChange: (value: string) => void;
  /** Initial focus state (the field tracks it itself afterwards). */
  typing?: boolean;
}

/** Variety input suggesting the catalog names of the crop; any other text is accepted with a notice. */
export function VarietyField(p: VarietyFieldProps) {
  const listId = `${p.id}-list`;
  const hasList = p.entries.length > 0;
  const [typing, setTyping] = useState(p.typing ?? false);
  return (
    <label className="block">
      <span className={LABEL}>{p.label}</span>
      <input id={p.id} type="text" value={p.value} list={hasList ? listId : undefined} autoComplete="off"
        onChange={(e) => p.onChange(e.target.value)}
        onFocus={() => setTyping(true)}
        onBlur={() => { setTyping(false); const next = varietyAfterBlur(p.value, p.entries); if (next !== null) p.onChange(next); }}
        className={INPUT} />
      {hasList && (
        <datalist id={listId}>{p.entries.map((e) => <option key={e.key} value={e.name} />)}</datalist>
      )}
      {isOutsideCatalog(p.value, p.entries, typing) && <span className="text-xs text-nkz-text-muted">{p.notice}</span>}
    </label>
  );
}
