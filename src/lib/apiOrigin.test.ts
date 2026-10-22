import { describe, it, expect, afterEach, vi } from 'vitest';

async function load() {
  vi.resetModules();
  return (await import('./apiOrigin')).API_ORIGIN;
}

describe('API_ORIGIN', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('uses window.__ENV__.VITE_API_URL without trailing slash', async () => {
    vi.stubGlobal('window', { __ENV__: { VITE_API_URL: 'https://api.example/' } });
    expect(`${await load()}/api/field-operations`).toBe('https://api.example/api/field-operations');
  });

  it('is empty (same-origin) without __ENV__', async () => {
    vi.stubGlobal('window', {});
    expect(`${await load()}/api/field-operations`).toBe('/api/field-operations');
  });
});
