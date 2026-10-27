/*
 * SPFx-style localisation: one folder per area (src/loc/<area>/), each with
 *   IStrings.ts   - the interface listing every string of that area (like SPFx mystrings.d.ts)
 *   en-in.ts      - English, typed against IStrings, so a missing or misspelled key fails the build
 *   hi-in.ts      - Hindi
 *   gu-in.ts, …   - more languages; a language switches on by itself once EVERY area has its file
 *   xx-in.draft.ts - work in progress (Partial<IStrings>), never loaded
 * English and Hindi are bundled; other languages load on demand when a visitor picks them.
 * Check coverage and unknown keys with `npm run i18n:check`.
 */
export type Dict = Record<string, string>;
type LocModule = { default: Dict };

const english = import.meta.glob<LocModule>('./*/en-in.ts', { eager: true });
const hindi = import.meta.glob<LocModule>('./*/hi-in.ts', { eager: true });
const others = import.meta.glob<LocModule>(['./*/*-in.ts', '!./*/en-in.ts', '!./*/hi-in.ts']);

const merge = (mods: LocModule[]): Dict => Object.assign({}, ...mods.map((m) => m.default));

/** Number of areas (folders with an English file). */
const AREA_COUNT = Object.keys(english).length;

export const EN: Dict = merge(Object.values(english));
export const HI: Dict = merge(Object.values(hindi));

/** Language code -> loaders of its per-area files, e.g. './place/gu-in.ts' -> 'gu'. */
const byLang: Record<string, (() => Promise<LocModule>)[]> = {};
for (const [path, loader] of Object.entries(others)) {
  const code = /\/([a-z]{2})-in\.ts$/.exec(path)?.[1];
  if (code) (byLang[code] ??= []).push(loader);
}

/** Extra languages that are complete in every area (so they are safe to offer). */
export const READY_LANGS: string[] = Object.keys(byLang).filter((code) => byLang[code].length === AREA_COUNT);

/** Load all area files of one extra language and merge them. */
export function loadLanguage(code: string): Promise<Dict> {
  return Promise.all((byLang[code] ?? []).map((load) => load())).then(merge);
}
