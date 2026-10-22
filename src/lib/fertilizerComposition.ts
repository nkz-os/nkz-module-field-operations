// Structured nutrient composition of a fertilization: N, P2O5 and K2O as % of the product.

export const NUTRIENT_FIELDS = ['nitrogenContent', 'phosphorusPentoxideContent', 'potassiumOxideContent'] as const;
export const NITROGEN_FORMS = ['ureic', 'ammoniacal', 'nitric', 'organic', 'mixed'] as const;
export type NitrogenForm = (typeof NITROGEN_FORMS)[number];

export type PercentParse = { kind: 'empty' } | { kind: 'ok'; value: number } | { kind: 'invalid' };

export type CompositionErrorKey =
  | 'fields.compositionNotANumber'
  | 'fields.compositionOutOfRange'
  | 'fields.compositionSumTooHigh';

export type CompositionResult =
  | { ok: true; body: Record<string, unknown> }
  | { ok: false; errorKey: CompositionErrorKey };

const PERCENT_TEXT = /^(\d+(\.\d*)?|\.\d+)$/;

/** A typed percentage. Accepts a decimal comma. Blank means "not recorded", never 0. */
export function parsePercentInput(raw: unknown): PercentParse {
  if (raw === undefined || raw === null) return { kind: 'empty' };
  if (typeof raw === 'number') return Number.isFinite(raw) ? { kind: 'ok', value: raw } : { kind: 'invalid' };
  if (typeof raw !== 'string') return { kind: 'invalid' };
  const text = raw.trim().replace(',', '.');
  if (text === '') return { kind: 'empty' };
  if (!PERCENT_TEXT.test(text)) return { kind: 'invalid' };
  return { kind: 'ok', value: Number(text) };
}

/** The fertilization form as a request body: contents as numbers, blanks left out. */
export function prepareFertilizationBody(form: Record<string, unknown>): CompositionResult {
  const body: Record<string, unknown> = { ...form };
  let total = 0;
  for (const field of NUTRIENT_FIELDS) {
    const parsed = parsePercentInput(form[field]);
    if (parsed.kind === 'empty') {
      delete body[field];
      continue;
    }
    if (parsed.kind === 'invalid') return { ok: false, errorKey: 'fields.compositionNotANumber' };
    if (parsed.value > 100) return { ok: false, errorKey: 'fields.compositionOutOfRange' };
    body[field] = parsed.value;
    total += parsed.value;
  }
  if (total > 100 + 1e-9) return { ok: false, errorKey: 'fields.compositionSumTooHigh' };
  if (!form.nitrogenForm) delete body.nitrogenForm;
  return { ok: true, body };
}

function attrValue(attr: unknown): unknown {
  if (attr !== null && typeof attr === 'object' && 'value' in attr) return (attr as { value: unknown }).value;
  return attr;
}

/** "15-15-15" for display; "?" where a content was not recorded; null when none was. */
export function formatGrade(op: Record<string, unknown>): string | null {
  const parts = NUTRIENT_FIELDS.map(field => attrValue(op[field]));
  if (parts.every(part => typeof part !== 'number')) return null;
  return parts.map(part => (typeof part === 'number' ? String(part) : '?')).join('-');
}

export function nitrogenFormOf(op: Record<string, unknown>): NitrogenForm | null {
  const value = attrValue(op.nitrogenForm);
  return typeof value === 'string' && (NITROGEN_FORMS as readonly string[]).includes(value)
    ? (value as NitrogenForm)
    : null;
}
