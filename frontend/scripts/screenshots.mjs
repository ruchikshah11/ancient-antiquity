/**
 * Take the README screenshots (docs/screenshots/visitor/*.png and docs/screenshots/admin/*.png) from the running dev servers.
 *   backend: python manage.py runserver 127.0.0.1:8000     frontend: npx vite --port 5173
 *   node scripts/screenshots.mjs                            (uses the installed Microsoft Edge)
 * Demo logins come from backend/.env (DEMO_ADMIN_PASSWORD, DEMO_VISITOR_PASSWORD).
 */
import { mkdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from '@playwright/test';

const BASE = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173';
const OUT = resolve(process.cwd(), '../docs/screenshots');
const PLACE = 'aga-khan-palace-pune';
for (const dir of ['visitor', 'admin']) mkdirSync(`${OUT}/${dir}`, { recursive: true });

const env = readFileSync(resolve(process.cwd(), '../backend/.env'), 'utf-8');
const secret = (key) => (env.split(/\r?\n/).find((l) => l.startsWith(`${key}=`)) ?? '').slice(key.length + 1).trim();
const ADMIN = { email: 'admin@ancientantiquity.in', password: secret('DEMO_ADMIN_PASSWORD') };
const VISITOR = { email: 'visitor@ancientantiquity.in', password: secret('DEMO_VISITOR_PASSWORD') };

const browser = await chromium.launch({ channel: 'msedge' });

async function session({ width = 1440, height = 900, lang = 'en', user = null } = {}) {
  const context = await browser.newContext({ viewport: { width, height }, locale: 'en-IN', timezoneId: 'Asia/Kolkata' });
  await context.addInitScript((l) => localStorage.setItem('aa_lang', l), lang);
  const page = await context.newPage();
  if (user) {
    await page.goto(`${BASE}/login`);
    const email = page.locator('#login-email');
    if (!(await email.isVisible().catch(() => false))) await page.getByRole('button', { name: /password/i }).first().click();
    await email.fill(user.email);
    await page.locator('#login-password').fill(user.password);
    await page.locator('#login-password').press('Enter');
    await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 });
  }
  return { context, page };
}

async function shot(page, name, path, { full = false, scrollTo = null } = {}) {
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(1500);
  if (scrollTo) {
    await page.locator(scrollTo).first().scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(800);
  }
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full });
  console.log(`  ${name}.png  ${path}`);
}

console.log('Visitor pages');
let { context, page } = await session();
await shot(page, 'visitor/home', '/');
await shot(page, 'visitor/explore', '/museums');
await shot(page, 'visitor/place', `/museums/${PLACE}`);
await shot(page, 'visitor/reviews', `/museums/${PLACE}`, { scrollTo: '#reviews, .reviews, h2:has-text("Reviews")' });
await shot(page, 'visitor/events', '/events');
await shot(page, 'visitor/heritage-map', '/map');
await shot(page, 'visitor/passes', '/passes');
await shot(page, 'visitor/membership', '/membership');
await shot(page, 'visitor/login', '/login');
await context.close();

({ context, page } = await session({ lang: 'hi' }));
await shot(page, 'visitor/hindi', '/');
await context.close();

({ context, page } = await session({ width: 390, height: 844 }));
await shot(page, 'visitor/mobile', '/');
await context.close();

({ context, page } = await session({ user: VISITOR }));
await shot(page, 'visitor/my-bookings', '/my-bookings');
await context.close();

console.log('Admin panel');
({ context, page } = await session({ user: ADMIN }));
for (const [name, path] of [
  ['admin/dashboard', '/admin'],
  ['admin/bookings', '/admin/bookings'],
  ['admin/places', '/admin/museums'],
  ['admin/place-editor', `/admin/museums/${PLACE}/edit`],
  ['admin/counter', '/admin/counter'],
  ['admin/checkin', '/admin/checkin'],
  ['admin/reports', '/admin/reports'],
  ['admin/users', '/admin/users'],
  ['admin/settings', '/admin/settings'],
  ['admin/pricing', '/admin/pricing'],
  ['admin/exports', '/admin/exports'],
]) {
  await shot(page, name, path);
}
await context.close();
await browser.close();
console.log(`Saved to ${OUT}`);
