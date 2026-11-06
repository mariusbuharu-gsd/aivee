import { expect, test } from '@playwright/test';
import { MOCK_PASSWORD, signIn } from '../helpers';

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
  await page.getByRole('button', { name: 'Ieși din cont' }).click();
  await expect(page.getByRole('heading', { name: 'Intră în cont' })).toBeVisible();
  await page.goto('/istoric');
  await expect(page).toHaveURL(/\/intra\?next=%2Fistoric/);
});

test('a seeded invite link creates the account and signs it in', async ({ page }) => {
  await page.goto('/invitatie/demo-invite');
  await expect(page.getByText('Terasa demo').first()).toBeVisible();
  await page.getByLabel(/Numele tău/).fill('Nou Venit');
  await page.locator('input[type=password]').first().fill('o-parola-lunga');
  await page.locator('button[type=submit]').click();
  await expect(page.getByRole('button', { name: 'Ieși din cont' })).toBeVisible();
  await expect(page.getByText('Nou Venit').first()).toBeAttached();
});
