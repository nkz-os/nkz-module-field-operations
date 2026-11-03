import { describe, expect, it, vi } from 'vitest';
vi.mock('@nekazari/sdk', () => ({ i18n: null }));
import { resources } from './i18n';
import { WOODY_EPPO } from './lib/woodySpecies';

const keys = (o: unknown, p = ''): string[] => Object.entries(o as Record<string, unknown>).flatMap(([k, v]) =>
  v && typeof v === 'object' ? keys(v, `${p}${k}.`) : [`${p}${k}`]);

describe('record form strings', () => {
  const en = keys((resources.en as Record<string, unknown>).record).sort();
  for (const [lang, res] of Object.entries(resources)) {
    it(`${lang} has every record key of en, and retry`, () => {
      const r = res as Record<string, unknown>;
      expect(keys(r.record).sort()).toEqual(en);
      expect(typeof r.retry).toBe('string');
    });
  }
});

describe('plantation strings', () => {
  const en = keys((resources.en as Record<string, unknown>).plantation).sort();
  for (const [lang, res] of Object.entries(resources)) {
    it(`${lang} has every plantation key of en`, () => {
      expect(keys((res as Record<string, unknown>).plantation).sort()).toEqual(en);
    });
  }
});

describe('woody species names', () => {
  for (const [lang, res] of Object.entries(resources)) {
    it(`${lang} names every woody species`, () => {
      const names = ((res as Record<string, any>).plantation.speciesNames) as Record<string, string>;
      for (const code of WOODY_EPPO) expect(typeof names[code]).toBe('string');
    });
  }
});
