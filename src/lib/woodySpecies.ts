/**
 * Woody species a plantation can be declared with (EPPO codes). Copied from the platform's
 * species registry (woody: true); the form never calls another module at runtime.
 * Display names live in the i18n resources (`plantation.speciesNames.<EPPO>`).
 */
export const WOODY_EPPO = ['OLVEU', 'VITVI', 'PRNDU', 'PIAVE', 'MABSD', 'PYUCO', 'PRNPS', 'PRNAR', 'PRNDO', 'PRNAV'] as const;

export type WoodyEppo = (typeof WOODY_EPPO)[number];

export function woodyOptions(t: (key: string) => string): { value: string; label: string }[] {
  return WOODY_EPPO.map((code) => ({ value: code, label: t(`plantation.speciesNames.${code}`) }));
}
