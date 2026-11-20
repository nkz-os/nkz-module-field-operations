import { describe, expect, it, vi } from 'vitest';
import {
  canonicalVariety, fetchVarietyCatalog, isOutsideCatalog, normalizeVarietyKey, type VarietyEntry,
} from './varietyCatalog';

const FILON: VarietyEntry = { name: 'FILON', key: 'FILON', cerealType: 'winter' };
const json = (status: number, body: unknown = {}) => ({ status, ok: status >= 200 && status < 300, json: async () => body }) as Response;

describe('normalizeVarietyKey (same as bioorch normalise_name)', () => {
  it.each([
    ['Filón', 'FILON'],
    ['  kiko   nick ', 'KIKO NICK'],
    ['Hispanic (T)', 'HISPANIC'],
    ['(T)', '(T)'],
    ['Año', 'ANO'],
    ['filón (t)', 'FILON'],
  ])('%s → %s', (raw, key) => { expect(normalizeVarietyKey(raw)).toBe(key); });
});

describe('canonicalVariety', () => {
  it('takes the catalog spelling when the key matches', () => {
    expect(canonicalVariety('filón (t)', [FILON])).toBe('FILON');
  });
  it('keeps an unknown text as typed', () => {
    expect(canonicalVariety('Nueva X', [FILON])).toBe('Nueva X');
  });
  it('keeps an empty text', () => {
    expect(canonicalVariety('', [FILON])).toBe('');
    expect(canonicalVariety('   ', [FILON])).toBe('   ');
  });
});

describe('isOutsideCatalog', () => {
  it('is true for a non-blank text outside a loaded list', () => {
    expect(isOutsideCatalog('Nueva X', [FILON])).toBe(true);
  });
  it('is false when the text matches, the list is empty or the text is blank', () => {
    expect(isOutsideCatalog('filon', [FILON])).toBe(false);
    expect(isOutsideCatalog('Nueva X', [])).toBe(false);
    expect(isOutsideCatalog('  ', [FILON])).toBe(false);
  });
});

describe('fetchVarietyCatalog', () => {
  it('maps a 200 answer', async () => {
    const f = vi.fn(async () => json(200, { varieties: [{ name: 'FILON', key: 'FILON', cereal_type: 'winter' },
      { name: 'Kiko', key: 'KIKO', cereal_type: null }] }));
    const out = await fetchVarietyCatalog('TRZAX', f as unknown as typeof fetch);
    expect(out).toEqual([FILON, { name: 'Kiko', key: 'KIKO', cerealType: null }]);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/graph\/planning\/varieties\?crop=TRZAX$/);
    expect(init.credentials).toBe('include');
  });
  it.each([401, 422, 503])('returns [] on %s', async (status) => {
    expect(await fetchVarietyCatalog('TRZAX', (async () => json(status)) as unknown as typeof fetch)).toEqual([]);
  });
  it('returns [] on a network error or a malformed body', async () => {
    expect(await fetchVarietyCatalog('TRZAX', (async () => { throw new Error('net'); }) as unknown as typeof fetch)).toEqual([]);
    expect(await fetchVarietyCatalog('TRZAX', (async () => json(200, {})) as unknown as typeof fetch)).toEqual([]);
    expect(await fetchVarietyCatalog('TRZAX', (async () => json(200, { varieties: [{ key: 'X' }] })) as unknown as typeof fetch)).toEqual([]);
  });
});
