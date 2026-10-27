import { expect, test } from '@playwright/test';
import { ADMIN, login } from './helpers';

test('admin signs in and opens the dashboard and reports', async ({ page }) => {
  await login(page, ADMIN);

  await page.goto('/admin');
  await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Recent bookings' })).toBeVisible();

  await page.goto('/admin/reports');
  await expect(page.getByRole('heading', { level: 1, name: 'Reports' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Daily revenue' })).toBeVisible();
});
