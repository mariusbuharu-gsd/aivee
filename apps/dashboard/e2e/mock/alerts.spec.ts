import { expect, test } from '@playwright/test';
import { MOCK_PASSWORD, signIn } from '../helpers';

// The mock opens "Masa 2" about 4 s after the page loads and closes it after 32 s.

test('an open alert offers no "Preiau": the camera closes it on its own', async ({ page }) => {
  await signIn(page, 'staff', MOCK_PASSWORD, '/alerte');
  const open = page.getByRole('list', { name: 'Alerte deschise' });
  await expect(open).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole('button', { name: /Preiau/ })).toHaveCount(0);
  // The mock closes "Masa 2" after 32 s by itself.
  await expect(open).toHaveCount(0, { timeout: 40_000 });
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

test('metrics show the wait and how many alerts it covers, no Preiau-based tiles', async ({
  page,
}) => {
  await signIn(page, 'manager', MOCK_PASSWORD, '/metrici');
  await expect(page.locator('.service-headline')).toContainText(/Clienții au așteptat de obicei/);
  await expect(page.locator('.service-lead')).toContainText(/Așteptare: .*din \d+ alert/);
  for (const label of ['Reacție', 'Drum']) {
    await expect(page.locator('.service-cell', { hasText: label })).toHaveCount(0);
  }
  await expect(page.getByText(/ținta ta · 1 min/)).toBeVisible();
});

test('the owner creates an invite link to copy', async ({ page }) => {
  await signIn(page, 'owner', MOCK_PASSWORD, '/echipa');
  await page.getByLabel('Email').fill('ospatar-nou@restaurant.ro');
  await page.getByRole('button', { name: /Creează linkul/ }).click();
  await expect(page.getByLabel('Link de invitație')).toHaveValue(/\/invitatie\/.+/);
});
