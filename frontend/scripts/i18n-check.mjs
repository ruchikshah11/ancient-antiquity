// Localisation check for the SPFx-style src/loc/<area>/ folders.
//   npm run i18n:check            every language + unknown keys used in the code
//   npm run i18n:check -- gu mr   only these languages
//   npm run i18n:check -- --dump  write English + Hindi (per area) to i18n-source.json for translators
// Fails (exit 1) when code uses a key English doesn't have, or a finished (non-draft) language file has problems.
import { buildSync } from 'esbuild';
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const root = resolve(import.meta.dirname, '..');
const locDir = join(root, 'src/loc');
const args = process.argv.slice(2);
const wanted = args.filter((a) => !a.startsWith('-'));
const cache = join(root, 'node_modules/.cache');
mkdirSync(cache, { recursive: true });
const tmp = mkdtempSync(join(cache, 'aa-i18n-'));

async function load(file) {
  const out = join(tmp, `${Math.random().toString(36).slice(2)}.mjs`);
  buildSync({ entryPoints: [file], bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'error' });
  return (await import(pathToFileURL(out).href)).default;
}

// Placeholder names, not counts: a bilingual line may repeat one ("Promo code {code} / प्रोमो कोड {code}").
const placeholders = (s) => [...new Set([...String(s).matchAll(/\{(\w+)\}/g)].map((m) => m[1]))].sort().join(',');

function sourceFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name !== 'loc') sourceFiles(p, out);
    } else if (/\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

let failed = false;
try {
  const areas = readdirSync(locDir).filter((d) => statSync(join(locDir, d)).isDirectory()).sort();
  const en = {};
  const perArea = {};
  for (const area of areas) {
    perArea[area] = { en: await load(join(locDir, area, 'en-in.ts')), hi: await load(join(locDir, area, 'hi-in.ts')) };
    Object.assign(en, perArea[area].en);
  }
  const total = Object.keys(en).length;

  if (args.includes('--dump')) {
    const file = join(root, 'i18n-source.json');
    writeFileSync(file, JSON.stringify(perArea, null, 1), 'utf-8');
    console.log(`${areas.length} areas, ${total} keys written to ${file}`);
    process.exit(0);
  }

  // 1. Keys used in the code must exist in English.
  const unknown = new Set();
  const prefixes = new Set();
  for (const file of sourceFiles(join(root, 'src'))) {
    const text = readFileSync(file, 'utf-8');
    for (const m of text.matchAll(/\bt\('([a-zA-Z0-9_.]+)'/g)) if (!(m[1] in en)) unknown.add(m[1]);
    for (const m of text.matchAll(/\bt\(`([a-zA-Z0-9_.]+)\$\{/g)) prefixes.add(m[1]);
  }
  const deadPrefixes = [...prefixes].filter((p) => !Object.keys(en).some((k) => k.startsWith(p)));
  if (unknown.size || deadPrefixes.length) {
    failed = true;
    console.log(`Code uses keys that English doesn't have: ${[...unknown, ...deadPrefixes.map((p) => `${p}*`)].join(', ')}`);
  } else {
    console.log(`Code keys: OK (${total} English strings in ${areas.length} areas)`);
  }

  // 2. Every language file against English, area by area.
  const langs = {};
  for (const area of areas) {
    for (const f of readdirSync(join(locDir, area))) {
      const m = /^([a-z]{2})-in(\.draft)?\.ts$/.exec(f);
      if (!m || m[1] === 'en') continue;
      if (wanted.length && !wanted.includes(m[1])) continue;
      const dict = await load(join(locDir, area, f));
      const ref = perArea[area].en;
      const lang = (langs[m[1]] ??= { complete: 0, drafts: [], keys: 0, problems: [] });
      const missing = Object.keys(ref).filter((k) => !(k in dict));
      const extra = Object.keys(dict).filter((k) => !(k in ref));
      const badVars = Object.keys(dict).filter((k) => k in ref && placeholders(dict[k]) !== placeholders(ref[k]));
      const empty = Object.keys(dict).filter((k) => !String(dict[k]).trim());
      lang.keys += Object.keys(dict).length - extra.length;
      if (m[2]) lang.drafts.push(area);
      else if (!missing.length) lang.complete += 1;
      for (const [label, list] of [['missing', missing], ['unknown', extra], ['placeholder mismatch', badVars], ['empty', empty]]) {
        if (list.length && !(m[2] && label === 'missing')) {
          lang.problems.push(`${area} ${label} (${list.length}): ${list.slice(0, 8).join(', ')}${list.length > 8 ? ' …' : ''}`);
          if (!m[2]) failed = true;
        }
      }
    }
  }
  for (const [code, l] of Object.entries(langs).sort()) {
    const ready = l.complete === areas.length;
    console.log(`${code}: ${l.keys}/${total} keys, ${l.complete}/${areas.length} areas complete${l.drafts.length ? `, drafts: ${l.drafts.length}` : ''} -> ${ready ? 'READY (offered to visitors)' : 'not offered yet'}`);
    for (const p of l.problems) console.log(`  ${p}`);
  }
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
process.exit(failed ? 1 : 0);
