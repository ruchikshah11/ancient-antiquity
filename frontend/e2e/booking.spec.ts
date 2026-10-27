import { expect, test } from '@playwright/test';
import { accessToken, login, PLACE_SLUG, VISITOR } from './helpers';

test('visitor books a ticket, pays with the demo gateway, sees the QR and cancels', async ({ page, request }) => {
  let reference = '';
  try {
    await login(page, VISITOR);

    // 1. Place page: first open date (pre-selected), first bookable slot, one ticket.
    await page.goto(`/museums/${PLACE_SLUG}`);
    await expect(page.getByRole('heading', { name: 'Book entry tickets' })).toBeVisible();
    await page.waitForLoadState('networkidle'); // date settles on the first open day, then slots reload
    const slot = page.locator('button.slot-btn:not([disabled])').first();
    await slot.click();
    await expect(slot).toHaveAttribute('aria-pressed', 'true');
    await page.locator('button[aria-label^="More "]').first().click();
    // Visitor details are prefilled from the account; fill whatever the demo account lacks (e.g. phone).
    for (const [id, value] of [['#v-name', 'Test Visitor'], ['#v-email', 'visitor@ancientantiquity.in'], ['#v-phone', '9876543210']]) {
      const input = page.locator(id);
      if ((await input.count()) && !(await input.inputValue())) await input.fill(value);
    }
    const submit = page.locator('form button.btn-accent.btn-lg');
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect(page.locator('form .alert-danger')).toHaveCount(0);

    // 2. Checkout with the demo gateway (no Razorpay keys in development), unless the ticket is free.
    await page.waitForURL(/\/(checkout|tickets)\/[A-Z0-9-]+/);
    reference = page.url().split('/').pop()!.split('?')[0];
    if (page.url().includes('/checkout/')) {
      await expect(page.getByText(/no real money|demo/i).first()).toBeVisible();
      await page.getByRole('button', { name: /^Pay / }).click();
      await page.waitForURL(new RegExp(`/tickets/${reference}`), { timeout: 30_000 });
    }

    // 3. Ticket with QR code.
    await expect(page.getByText(reference).first()).toBeVisible();
    await expect(page.locator(`svg[height="150"]`)).toBeVisible(); // QRCodeSVG size={150}

    // 4. Cancel (accept the confirmation dialog) so no booking is left behind.
    page.once('dialog', (d) => void d.accept());
    await page.getByRole('button', { name: 'Cancel booking' }).click();
    await expect(page.getByText(/cancelled/i).first()).toBeVisible();
    const token = await accessToken(page);
    const res = await request.get(`/api/bookings/${reference}/`, { headers: { Authorization: `Bearer ${token}` } });
    expect(res.ok()).toBeTruthy();
    expect((await res.json()).status).toBe('cancelled');
    reference = ''; // cleaned up
  } finally {
    // Safety net: if any step failed after the booking was created, cancel it through the API.
    if (reference) {
      const token = await accessToken(page).catch(() => '');
      await request
        .post(`/api/bookings/${reference}/cancel/`, { headers: { Authorization: `Bearer ${token}` } })
        .catch(() => undefined);
    }
  }
});
