import { useEffect, useRef, useState } from 'react';
import { API_ORIGIN } from './apiOrigin';
import { bearerHeaders } from './recordModel';

/** One variety of bioorch's catalog: `name` is the graph's spelling, the one a form stores. */
export type VarietyEntry = { name: string; key: string; cerealType: 'winter' | 'spring' | null };

/** The same key as bioorch's `normalise_name`: uppercase, no trailing "(tag)", no accents, single spaces. */
export function normalizeVarietyKey(raw: string): string {
  const upper = raw.trim().toUpperCase();
  const untagged = upper.replace(/\s*\([^)]*\)\s*$/, '').trim();
  const base = untagged || upper;
  return base.normalize('NFKD').replace(/\p{M}/gu, '').replace(/\s+/g, ' ').trim().toUpperCase();
}

function find(text: string, entries: VarietyEntry[]): VarietyEntry | undefined {
  if (!text.trim()) return undefined;
  const key = normalizeVarietyKey(text);
  return entries.find((e) => e.key === key);
}

/** The catalog spelling when the text is a catalog variety; otherwise the text as typed. */
export function canonicalVariety(text: string, entries: VarietyEntry[]): string {
  return find(text, entries)?.name ?? text;
}

/** A typed variety the catalog does not know (only once a non-empty list is loaded). */
export function isOutsideCatalog(text: string, entries: VarietyEntry[]): boolean {
  return entries.length > 0 && text.trim() !== '' && find(text, entries) === undefined;
}

/** Catalog of a crop; [] on any failure, so the field stays free text. */
export async function fetchVarietyCatalog(crop: string, fetchImpl: typeof fetch = fetch): Promise<VarietyEntry[]> {
  try {
    const resp = await fetchImpl(`${API_ORIGIN}/api/graph/planning/varieties?crop=${encodeURIComponent(crop)}`, {
      credentials: 'include',
      headers: bearerHeaders(typeof window !== 'undefined' ? (window as unknown as { keycloak?: { token?: string } }) : undefined),
    });
    if (!resp.ok) return [];
    const body = (await resp.json()) as { varieties?: unknown };
    if (!Array.isArray(body?.varieties)) return [];
    const out: VarietyEntry[] = [];
    for (const v of body.varieties as Record<string, unknown>[]) {
      if (typeof v?.name !== 'string' || typeof v?.key !== 'string' || !v.name) continue;
      const ct = v.cereal_type === 'winter' || v.cereal_type === 'spring' ? v.cereal_type : null;
      out.push({ name: v.name, key: v.key, cerealType: ct });
    }
    return out;
  } catch {
    return [];
  }
}

/** The form with its variety in the catalog spelling (same object when nothing changes). */
export function withCanonicalVariety<T extends { variety: string }>(form: T, entries: VarietyEntry[]): T {
  const variety = canonicalVariety(form.variety, entries);
  return variety === form.variety ? form : { ...form, variety };
}

/** Loads one crop's catalog at a time: clears at once on every change and drops answers for an older crop. */
export function createCatalogLoader(fetchFn: (crop: string) => Promise<VarietyEntry[]>,
  onEntries: (entries: VarietyEntry[]) => void): { load: (crop: string | null) => Promise<void> } {
  let token = 0;
  return {
    async load(crop) {
      const mine = ++token;
      onEntries([]);
      if (!crop) return;
      const entries = await fetchFn(crop);
      if (mine === token) onEntries(entries);
    },
  };
}

/** The catalog of the chosen crop for a variety field; [] while loading, without a crop or on failure. */
export function useVarietyCatalog(crop: string | null): VarietyEntry[] {
  const [entries, setEntries] = useState<VarietyEntry[]>([]);
  const loader = useRef(createCatalogLoader((c) => fetchVarietyCatalog(c), setEntries));
  useEffect(() => { void loader.current.load(crop); }, [crop]);
  return entries;
}
