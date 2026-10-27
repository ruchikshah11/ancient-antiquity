import { expect, test } from '@playwright/test';
import { PLACE_SLUG } from './helpers';

test.describe('visitor pages (signed out)', () => {
  test('home loads and the language switches to Hindi and back', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toContainText("five thousand years of India's story");

    // The globe menu holds every language (and the currency); pick Hindi, then English again.
    await page.locator('.prefs-toggle').click();
    await page.locator('.prefs-panel').getByRole('button', { name: /हिन्दी/ }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'hi');
    await expect(page.locator('.prefs-toggle')).toContainText('HI');
    await expect(page.getByRole('heading', { level: 1 })).not.toContainText("five thousand years of India's story");

    await page.locator('.prefs-toggle').click();
    await page.locator('.prefs-panel').getByRole('button', { name: /English/ }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.getByRole('heading', { level: 1 })).toContainText("five thousand years of India's story");
  });

  test('explore filters (type chip and state) change the result count', async ({ page }) => {
    await page.goto('/museums');
    const found = page.getByText(/\d+ places? found/);
    await expect(found).toBeVisible();
    const total = Number((await found.textContent())!.match(/\d+/)![0]);
    expect(total).toBeGreaterThan(1);

    // Type chip: "Forts"
    const types = page.getByRole('group', { name: 'Type of place' });
    await types.getByRole('button', { name: /^Forts/ }).click();
    await expect(page).toHaveURL(/type=fort/);
    await expect(found).not.toHaveText(`${total} places found`);
    const forts = Number((await found.textContent())!.match(/\d+/)![0]);
    expect(forts).toBeGreaterThan(0);
    expect(forts).toBeLessThan(total);

    // State filter: pick the first state that still has places.
    const state = page.getByRole('combobox', { name: 'State' });
    const option = state.locator('option:not([value=""]):not([disabled])').first();
    const value = (await option.getAttribute('value'))!;
    await state.selectOption(value);
    await expect(page).toHaveURL(new RegExp(`state=${value}`));
    await expect(found).not.toHaveText(`${forts} places found`);
    const narrowed = Number((await found.textContent())!.match(/\d+/)![0]);
    expect(narrowed).toBeLessThanOrEqual(forts);

    // Back to all places.
    await types.getByRole('button', { name: /^All/ }).click();
    await expect(page).not.toHaveURL(/type=fort/);
  });

  test('place page shows the booking card with slot buttons', async ({ page }) => {
    await page.goto(`/museums/${PLACE_SLUG}`);
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Aga Khan Palace');
    await expect(page.getByRole('heading', { name: 'Book entry tickets' })).toBeVisible();
    await expect(page.locator('#visit-date')).toHaveValue(/\d{4}-\d{2}-\d{2}/);
    const slots = page.locator('button.slot-btn');
    await expect(slots.first()).toBeVisible();
    expect(await slots.count()).toBeGreaterThan(0);
    await expect(page.locator('button.slot-btn:not([disabled])').first()).toBeVisible();
  });
});

test('app is installable: manifest, icons and theme colour are linked', async ({ page, request }) => {
  await page.goto('/');
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute('href', '/manifest.webmanifest');
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#0277bd');
  const manifest = await (await request.get('/manifest.webmanifest')).json();
  expect(manifest.short_name).toBe('Antiquity');
  expect(manifest.display).toBe('standalone');
  for (const icon of manifest.icons as { src: string }[]) {
    const res = await request.get(icon.src);
    expect(res.ok(), icon.src).toBeTruthy();
    expect(res.headers()['content-type']).toContain('image/png');
  }
  const key = await request.get('/api/notifications/push/public-key/');
  expect(key.ok()).toBeTruthy();
  expect(await key.json()).toHaveProperty('public_key');
});
