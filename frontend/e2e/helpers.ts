import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, type Page } from '@playwright/test';

/** Demo passwords live in backend/.env (DEMO_*_PASSWORD), never in the source. */
function demoPassword(role: 'ADMIN' | 'VISITOR'): string {
  const key = `DEMO_${role}_PASSWORD`;
  if (process.env[key]) return process.env[key] as string;
  const env = readFileSync(resolve(process.cwd(), '../backend/.env'), 'utf-8');
  const line = env.split(/\r?\n/).find((l) => l.startsWith(`${key}=`));
  if (!line) throw new Error(`${key} is missing from backend/.env`);
  return line.slice(key.length + 1).trim();
}

export const VISITOR = { email: 'visitor@ancientantiquity.in', password: demoPassword('VISITOR') };
export const ADMIN = { email: 'admin@ancientantiquity.in', password: demoPassword('ADMIN') };

/** A seeded place with paid tickets (starting price Rs 25). */
export const PLACE_SLUG = 'aga-khan-palace-pune';

/** Sign in through the login page (password form). */
export async function login(page: Page, user: { email: string; password: string }): Promise<void> {
  await page.goto('/login');
  const email = page.locator('#login-email');
  if (!(await email.isVisible().catch(() => false))) {
    // The page may open on another sign-in method (one-time code); switch to the password form.
    await page.getByRole('button', { name: /password/i }).first().click();
  }
  await email.fill(user.email);
  await page.locator('#login-password').fill(user.password);
  await page.locator('#login-password').press('Enter');
  await expect(page).not.toHaveURL(/\/login/);
  await expect.poll(() => page.evaluate(() => localStorage.getItem('aa_access'))).not.toBeNull();
}

/** Bearer token of the signed-in browser session (for API clean-up calls). */
export async function accessToken(page: Page): Promise<string> {
  return (await page.evaluate(() => localStorage.getItem('aa_access'))) ?? '';
}
