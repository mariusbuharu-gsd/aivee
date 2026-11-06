import { expect, test, type Page } from '@playwright/test';
import { MANAGER_NAV, OWNER_NAV, STAFF_NAV, navLinks, signIn } from '../helpers';

// Against a running API seeded with `make seed`. Run with `npm run e2e:real`.
// Read-only on purpose except "Merg eu", which only writes the audit log (no Telegram).

const password = process.env.DEMO_PASSWORD ?? '';
test.skip(!password, 'DEMO_PASSWORD is not set');

/** API calls answered with an error, so a test can assert the page asked only for what it may. */
function apiErrors(page: Page) {
  const errors: string[] = [];
  const api = process.env.E2E_API_URL ?? 'http://localhost:8000';
  page.on('response', (r) => {
    const url = r.url();
    if (!url.startsWith(api) || r.status() < 400) return;
    if (r.status() === 401 && url.endsWith('/api/auth/me')) return; // the anonymous probe on load
    errors.push(`${r.status()} ${r.request().method()} ${url.slice(api.length)}`);
  });
  return errors;
}

test('the owner sees every page and the org owners in the team list', async ({ page }) => {
  const errors = apiErrors(page);
  await signIn(page, 'owner', password);
  expect(await navLinks(page)).toEqual(OWNER_NAV);
  for (const path of ['/alerte', '/metrici', '/istoric', '/echipa', '/locatii']) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  }
  await page.goto('/echipa');
  await expect(page.locator('.member', { hasText: 'owner@aivee.demo' })).toContainText(
    /proprietar/i,
  );
  expect(errors).toEqual([]);
});

test('a manager gets rules and team but not locations', async ({ page }) => {
  const errors = apiErrors(page);
  await signIn(page, 'manager', password);
  expect(await navLinks(page)).toEqual(MANAGER_NAV);
  await page.goto('/locatii');
  await expect(page).toHaveURL(/\/$/);
  await page.goto('/istoric');
  await expect(page.locator('.audit-row').first()).toBeVisible();
  expect(errors).toEqual([]);
});

test('staff load alerts without forbidden calls and can take an open one', async ({ page }) => {
  const errors = apiErrors(page);
  await signIn(page, 'staff', password, '/alerte');
  expect(await navLinks(page)).toEqual(STAFF_NAV);
  await expect(page.getByRole('heading', { name: 'Alerte', level: 1 })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(errors).toEqual([]);

  const go = page.getByRole('button', { name: /Merg eu la/ }).first();
  if (!(await go.isVisible().catch(() => false))) {
    test.info().annotations.push({ type: 'note', description: 'no open alert to take' });
    return;
  }
  await go.evaluate((el) => el.closest('li')?.setAttribute('data-e2e', 'taken'));
  const card = page.locator('li[data-e2e="taken"]');
  await go.click();
  await expect(card.getByRole('list', { name: 'Desfășurarea alertei' })).toContainText('Preluată');
  expect(errors).toEqual([]);
});
