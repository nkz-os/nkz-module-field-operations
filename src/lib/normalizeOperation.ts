import type { Operation } from '../components/OperationCard';

// The list endpoint answers in NGSI-LD keyValues ("status": "planned"), while the components
// read the normalized form ({ value } / { object }). Normalize once, where the list is fetched.

const ATTRIBUTE_TYPES = new Set([
  'Property', 'Relationship', 'GeoProperty', 'LanguageProperty', 'VocabProperty', 'ListProperty',
]);
const RELATIONSHIP = /^(has|ref)[A-Z]/;

function isNormalized(attr: unknown): boolean {
  if (attr === null || typeof attr !== 'object' || Array.isArray(attr)) return false;
  return ATTRIBUTE_TYPES.has(String((attr as { type?: unknown }).type));
}

export function normalizeOperation(entity: Record<string, unknown>): Operation {
  const out: Record<string, unknown> = {};
  for (const [key, attr] of Object.entries(entity)) {
    if (key === 'id' || key === 'type' || key === '@context' || isNormalized(attr)) out[key] = attr;
    else if (RELATIONSHIP.test(key)) out[key] = { type: 'Relationship', object: attr };
    else out[key] = { type: 'Property', value: attr };
  }
  // The platform @context aliases hasAgriParcel to refAgriParcel, so Orion answers with the old name.
  if (out.hasAgriParcel === undefined && out.refAgriParcel !== undefined) out.hasAgriParcel = out.refAgriParcel;
  return out as Operation;
}
