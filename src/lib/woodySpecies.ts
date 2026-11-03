/**
 * Woody species a plantation can be declared with (EPPO codes). Copied from the platform's
 * species registry (woody: true); the form never calls another module at runtime.
 */
export const WOODY_EPPO = ['OLVEU', 'VITVI', 'PRNDU', 'PIAVE', 'MABSD', 'PYUCO', 'PRNPS', 'PRNAR', 'PRNDO', 'PRNAV'] as const;

export type WoodyEppo = (typeof WOODY_EPPO)[number];

/** Common names by language; any other language falls back to English. */
export const WOODY_NAMES: Record<string, Record<WoodyEppo, string>> = {
  en: { OLVEU: 'Olive', VITVI: 'Grapevine', PRNDU: 'Almond', PIAVE: 'Pistachio', MABSD: 'Apple', PYUCO: 'Pear',
    PRNPS: 'Peach', PRNAR: 'Apricot', PRNDO: 'Plum', PRNAV: 'Cherry' },
  es: { OLVEU: 'Olivo', VITVI: 'Vid', PRNDU: 'Almendro', PIAVE: 'Pistachero', MABSD: 'Manzano', PYUCO: 'Peral',
    PRNPS: 'Melocotonero', PRNAR: 'Albaricoquero', PRNDO: 'Ciruelo', PRNAV: 'Cerezo' },
  ca: { OLVEU: 'Olivera', VITVI: 'Vinya', PRNDU: 'Ametller', PIAVE: 'Pistatxer', MABSD: 'Pomera', PYUCO: 'Perera',
    PRNPS: 'Presseguer', PRNAR: 'Albercoquer', PRNDO: 'Prunera', PRNAV: 'Cirerer' },
  eu: { OLVEU: 'Olibondoa', VITVI: 'Mahatsondoa', PRNDU: 'Almendrondoa', PIAVE: 'Pistatxondoa', MABSD: 'Sagarrondoa',
    PYUCO: 'Udareondoa', PRNPS: 'Muxikondoa', PRNAR: 'Abrikotondoa', PRNDO: 'Aranondoa', PRNAV: 'Gerezondoa' },
  fr: { OLVEU: 'Olivier', VITVI: 'Vigne', PRNDU: 'Amandier', PIAVE: 'Pistachier', MABSD: 'Pommier', PYUCO: 'Poirier',
    PRNPS: 'Pêcher', PRNAR: 'Abricotier', PRNDO: 'Prunier', PRNAV: 'Cerisier' },
  pt: { OLVEU: 'Oliveira', VITVI: 'Videira', PRNDU: 'Amendoeira', PIAVE: 'Pistacheiro', MABSD: 'Macieira', PYUCO: 'Pereira',
    PRNPS: 'Pessegueiro', PRNAR: 'Damasqueiro', PRNDO: 'Ameixoeira', PRNAV: 'Cerejeira' },
};

export function woodyOptions(lang: string): { value: string; label: string }[] {
  const names = WOODY_NAMES[lang] ?? WOODY_NAMES.en;
  return WOODY_EPPO.map((code) => ({ value: code, label: names[code] }));
}
