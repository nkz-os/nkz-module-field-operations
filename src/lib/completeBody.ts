/** The calendar day of `now` at the user's place, as YYYY-MM-DD. */
export function localDay(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

/** The payload of a completion: the form fields plus the day the work was done. */
export function buildCompleteBody(
  payload: Record<string, unknown>,
  completedOn: string,
): Record<string, unknown> {
  return completedOn ? { ...payload, completedOn } : { ...payload };
}

const DATE_ERRORS: Record<string, string> = {
  invalid_date: 'form.invalidDate',
  future_date: 'form.futureDate',
};

/** The i18n key for an API error code about the completion date, or null for any other. */
export function dateErrorKey(code: unknown): string | null {
  return typeof code === 'string' ? (DATE_ERRORS[code] ?? null) : null;
}
