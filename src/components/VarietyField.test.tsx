import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { VarietyField, varietyAfterBlur } from './VarietyField';
import type { VarietyEntry } from '../lib/varietyCatalog';

const FILON: VarietyEntry = { name: 'FILON', key: 'FILON', cerealType: 'winter' };
const KIKO: VarietyEntry = { name: 'Kiko Nick', key: 'KIKO NICK', cerealType: null };

const field = (value: string, entries: VarietyEntry[]) => renderToStaticMarkup(
  <VarietyField id="record-variety" label="Variedad" value={value} entries={entries} notice="NOT_IN_CATALOG"
    onChange={() => {}} />);

describe('VarietyField', () => {
  it('offers the catalog names in a datalist bound to the input', () => {
    const h = field('', [FILON, KIKO]);
    expect(h).toContain('id="record-variety"');
    expect(h).toContain('list="record-variety-list"');
    expect(h).toContain('<datalist id="record-variety-list"><option value="FILON"></option><option value="Kiko Nick"></option></datalist>');
  });
  it('shows the notice for a variety outside a loaded list', () => {
    expect(field('Nueva X', [FILON])).toContain('NOT_IN_CATALOG');
  });
  it('no notice for a catalog variety, an empty list or an empty field', () => {
    expect(field('filon', [FILON])).not.toContain('NOT_IN_CATALOG');
    expect(field('Nueva X', [])).not.toContain('NOT_IN_CATALOG');
    expect(field('', [FILON])).not.toContain('NOT_IN_CATALOG');
  });
  it('no datalist without a list (plain free text, as before)', () => {
    expect(field('x', [])).not.toContain('<datalist');
  });
});

describe('VarietyField while typing', () => {
  it('no notice for the start of a catalog name while the field has focus', () => {
    const h = renderToStaticMarkup(<VarietyField id="v" label="L" value="FIL" entries={[FILON]} notice="NOT_IN_CATALOG"
      onChange={() => {}} typing />);
    expect(h).not.toContain('NOT_IN_CATALOG');
  });
});

describe('varietyAfterBlur', () => {
  it('returns the catalog spelling only when it differs', () => {
    expect(varietyAfterBlur('filon', [FILON])).toBe('FILON');
    expect(varietyAfterBlur('FILON', [FILON])).toBeNull();
    expect(varietyAfterBlur('Nueva X', [FILON])).toBeNull();
  });
});
