import { expect, test } from '@playwright/test';
import { MOCK_PASSWORD, signIn } from '../helpers';

// The mock opens "Masa 2" about 4 s after the page loads and closes it after 32 s.

test('staff take an open alert with "Merg eu" and the timeline shows who and how fast', async ({
  page,
}) => {
  await signIn(page, 'staff', MOCK_PASSWORD, '/alerte');
  const go = page.getByRole('button', { name: /Merg eu la/ }).first();
  await expect(go).toBeVisible({ timeout: 20_000 });
  // The button disappears once taken, so pin the card itself before clicking.
  await go.evaluate((el) => el.closest('li')?.setAttribute('data-e2e', 'taken'));
  const card = page.locator('li[data-e2e="taken"]');
  await go.click();
  await expect(page.getByText('Ai preluat Masa 2')).toBeVisible();
  await expect(card.getByRole('button', { name: /Merg eu/ })).toHaveCount(0);
  const timeline = card.getByRole('list', { name: 'Desfășurarea alertei' });
  await expect(timeline).toContainText('Preluată');
  await expect(timeline).toContainText('Ana Dumitru');
  await expect(timeline).toContainText(/reacție \d+/);
  // The mock lets Ana "arrive" 4 s after she pressed the button.
  await expect(timeline).toContainText(/drum \d+/, { timeout: 10_000 });
});

test('the history filters by kind and keeps the period', async ({ page }) => {
  await signIn(page, 'owner', MOCK_PASSWORD, '/istoric');
  await expect(page.getByText(/a confirmat că #7 e din personal/)).toBeVisible();
  // One alert is one row: its timeline and total, the raw entries folded inside.
  const thread = page.locator('.audit-row.is-thread', { hasText: 'Masa 1' });
  await expect(thread.getByRole('list', { name: /Cronologia alertei/ })).toContainText('închisă');
  await expect(thread).toContainText('în total');
  await page.getByRole('group', { name: 'Tip' }).getByRole('button', { name: 'Reguli' }).click();
  await expect(page.getByText(/a schimbat regula/)).toBeVisible();
  await expect(page.getByText(/a confirmat că #7/)).toHaveCount(0);
});

test('metrics show wait, reaction and travel with how many alerts they cover', async ({ page }) => {
  await signIn(page, 'manager', MOCK_PASSWORD, '/metrici');
  for (const label of ['Așteptare', 'Reacție', 'Drum']) {
    await expect(page.locator('.service-cell', { hasText: label })).toContainText(/din \d+ alert/);
  }
});

test('the owner creates an invite link to copy', async ({ page }) => {
  await signIn(page, 'owner', MOCK_PASSWORD, '/echipa');
  await page.getByLabel('Email').fill('ospatar-nou@restaurant.ro');
  await page.getByRole('button', { name: /Creează linkul/ }).click();
  await expect(page.getByLabel('Link de invitație')).toHaveValue(/\/invitatie\/.+/);
});
