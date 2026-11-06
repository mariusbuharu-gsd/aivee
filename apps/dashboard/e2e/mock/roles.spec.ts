import { expect, test } from '@playwright/test';
import { MANAGER_NAV, MOCK_PASSWORD, OWNER_NAV, STAFF_NAV, navLinks, signIn } from '../helpers';

test('staff see alerts but no configuration, and direct links bounce back', async ({ page }) => {
  await signIn(page, 'staff', MOCK_PASSWORD);
  expect(await navLinks(page)).toEqual(STAFF_NAV);
  for (const path of ['/reguli', '/echipa', '/locatii', '/dispozitive']) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/$/);
  }
  await expect(page.locator('.banner-error')).toHaveCount(0);
});

test('a manager runs one location: rules and team, but not locations', async ({ page }) => {
  await signIn(page, 'manager', MOCK_PASSWORD);
  expect(await navLinks(page)).toEqual(MANAGER_NAV);
  await page.goto('/echipa');
  await expect(page.getByText('Ioana Popescu')).toBeVisible();
  // Managers invite staff only.
  await expect(page.getByRole('radio', { name: 'Manager' })).toHaveCount(0);
});

test('the owner switches location and every page follows', async ({ page }) => {
  await signIn(page, 'owner', MOCK_PASSWORD);
  expect(await navLinks(page)).toEqual(OWNER_NAV);
  const switcher = page.getByLabel('Locația');
  await expect(switcher).toHaveValue('demo');
  await switcher.selectOption('centru');
  await page.goto('/echipa');
  await expect(page.getByLabel('Locația')).toHaveValue('centru');
  await expect(page.locator('main')).toContainText('Bistro Centru');
});
