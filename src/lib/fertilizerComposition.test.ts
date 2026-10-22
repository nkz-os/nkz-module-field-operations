import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  formatGrade, nitrogenFormOf, parsePercentInput, prepareFertilizationBody,
} from './fertilizerComposition';

describe('parsePercentInput', () => {
  it('treats a blank as not recorded, never as 0', () => {
    expect(parsePercentInput('')).toEqual({ kind: 'empty' });
    expect(parsePercentInput('   ')).toEqual({ kind: 'empty' });
    expect(parsePercentInput(undefined)).toEqual({ kind: 'empty' });
  });
  it('accepts a decimal comma', () => {
    expect(parsePercentInput('15,5')).toEqual({ kind: 'ok', value: 15.5 });
  });
  it('keeps an explicit 0', () => {
    expect(parsePercentInput('0')).toEqual({ kind: 'ok', value: 0 });
  });
  it('rejects text, negatives, exponents and stray symbols', () => {
    for (const raw of ['abc', '-3', '1e2', '15%', '1,2,3']) {
      expect(parsePercentInput(raw)).toEqual({ kind: 'invalid' });
    }
  });
});

describe('prepareFertilizationBody', () => {
  it('leaves blank contents and an unset form out of the body', () => {
    expect(prepareFertilizationBody({
      fertilizerRate: 300, nitrogenContent: '', phosphorusPentoxideContent: '15,5', nitrogenForm: '',
    })).toEqual({ ok: true, body: { fertilizerRate: 300, phosphorusPentoxideContent: 15.5 } });
  });
  it('sends an explicit 0 and the chosen nitrogen form', () => {
    expect(prepareFertilizationBody({ potassiumOxideContent: '0', nitrogenForm: 'nitric' }))
      .toEqual({ ok: true, body: { potassiumOxideContent: 0, nitrogenForm: 'nitric' } });
  });
  it('flags a content that is not a number', () => {
    expect(prepareFertilizationBody({ nitrogenContent: 'quince' }))
      .toEqual({ ok: false, errorKey: 'fields.compositionNotANumber' });
  });
  it('flags a content above 100', () => {
    expect(prepareFertilizationBody({ nitrogenContent: '120' }))
      .toEqual({ ok: false, errorKey: 'fields.compositionOutOfRange' });
  });
  it('flags a grade adding up to more than 100', () => {
    expect(prepareFertilizationBody({
      nitrogenContent: '50', phosphorusPentoxideContent: '50', potassiumOxideContent: '1',
    })).toEqual({ ok: false, errorKey: 'fields.compositionSumTooHigh' });
  });
});

describe('formatGrade', () => {
  it('reads both the normalized and the keyValues entity shapes', () => {
    expect(formatGrade({
      nitrogenContent: { value: 15 }, phosphorusPentoxideContent: 15,
      potassiumOxideContent: { value: 15, unitCode: 'P1' },
    })).toBe('15-15-15');
  });
  it('marks a content that was not recorded', () => {
    expect(formatGrade({ nitrogenContent: 27 })).toBe('27-?-?');
  });
  it('is null when nothing was recorded', () => {
    expect(formatGrade({})).toBeNull();
  });
});

describe('nitrogenFormOf', () => {
  it('returns a declared form and ignores anything else', () => {
    expect(nitrogenFormOf({ nitrogenForm: { value: 'nitric' } })).toBe('nitric');
    expect(nitrogenFormOf({ nitrogenForm: 'nitrate' })).toBeNull();
  });
});

describe('translations', () => {
  const keys = ['nitrogenContent', 'phosphorusPentoxideContent', 'potassiumOxideContent', 'nitrogenForm',
    'compositionGrade', 'compositionNotANumber', 'compositionOutOfRange', 'compositionSumTooHigh'];
  for (const lang of ['es', 'en', 'ca', 'eu', 'fr', 'pt']) {
    it(`${lang} has every composition key`, () => {
      const fields = JSON.parse(readFileSync(`i18n/${lang}/translation.json`, 'utf8')).fields;
      for (const key of keys) expect(typeof fields[key], `${lang}.fields.${key}`).toBe('string');
      for (const form of ['ureic', 'ammoniacal', 'nitric', 'organic', 'mixed']) {
        expect(typeof fields.nitrogenForms?.[form], `${lang}.fields.nitrogenForms.${form}`).toBe('string');
      }
    });
  }
});
