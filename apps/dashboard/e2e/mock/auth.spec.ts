import { expect, test } from '@playwright/test';
import { MOCK_PASSWORD, STAFF_NAV, navLinks, openMore, signIn, signOut } from '../helpers';

test('a demo role card signs in with one click', async ({ page }) => {
  await page.goto('/intra');
  const demo = page.getByRole('group', { name: /Încearcă un cont demo/ });
  await demo.getByRole('button', { name: /Ospătar/ }).click();
  await expect(page.getByRole('navigation', { name: 'Principal' })).toBeVisible();
  expect(await navLinks(page)).toEqual(STAFF_NAV);
});

test('an anonymous visit goes to the login page and comes back after signing in', async ({
  page,
}) => {
  await signIn(page, 'manager', MOCK_PASSWORD, '/alerte');
  await expect(page).toHaveURL(/\/alerte$/);
  await expect(page.getByRole('heading', { name: 'Alerte', level: 1 })).toBeVisible();
});

test('a wrong password shows a Romanian error and keeps the user on the login page', async ({
  page,
}) => {
  await page.goto('/intra');
  await page.getByLabel('Email').fill('staff@aivee.demo');
  await page.getByLabel('Parolă', { exact: true }).fill('nu-e-bună');
  await page.getByRole('button', { name: 'Intră în cont' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page).toHaveURL(/\/intra/);
});

test('signing out returns to the login page and guards the app again', async ({ page }) => {
  await signIn(page, 'staff', MOCK_PASSWORD);
  await signOut(page);
  await expect(page.getByRole('heading', { name: 'Intră în cont' })).toBeVisible();
  await page.goto('/istoric');
  await expect(page).toHaveURL(/\/intra\?next=%2Fistoric/);
});

test('a seeded invite link creates the account and signs it in', async ({ page }) => {
  await page.goto('/invitatie/demo-invite');
  await expect(page.getByText('Terasa demo').first()).toBeVisible();
  await page.getByLabel(/Numele tău/).fill('Nou Venit');
  await page.getByLabel('Parolă', { exact: true }).fill('o-parola-lunga');
  await page.getByRole('button', { name: 'Arată parola' }).click();
  await expect(page.getByLabel('Parolă', { exact: true })).toHaveAttribute('type', 'text');
  await page.locator('button[type=submit]').click();
  await expect(page.getByRole('navigation', { name: 'Principal' })).toBeVisible();
  await openMore(page);
  await expect(page.getByText('Nou Venit').first()).toBeAttached();
});
