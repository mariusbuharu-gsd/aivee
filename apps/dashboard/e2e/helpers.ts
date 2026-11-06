import { expect, type Page } from '@playwright/test';

export type DemoUser = 'owner' | 'manager' | 'staff';

/** The mock accepts this password for every demo user (src/api/mockAccounts.ts). */
export const MOCK_PASSWORD = 'demo1234';

export const email = (who: DemoUser) => `${who}@aivee.demo`;

/** Sign in through the login form and wait until the app shell is up. */
export async function signIn(page: Page, who: DemoUser, password: string, path = '/') {
  await page.goto(path);
  await expect(page).toHaveURL(/\/intra/);
  await page.getByLabel('Email').fill(email(who));
  await page.getByLabel('Parolă', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Intră în cont' }).click();
  await expect(page.getByRole('button', { name: 'Ieși din cont' })).toBeVisible({
    timeout: 20_000,
  });
}

/** Link texts in the main navigation, without the alert counter badge. */
export async function navLinks(page: Page): Promise<string[]> {
  const links = page.getByRole('navigation', { name: 'Principal' }).getByRole('link');
  await expect(links.first()).toBeVisible();
  return (await links.allTextContents()).map((t) => t.replace(/\d+$/, '').trim());
}

export const STAFF_NAV = ['Live', 'Alerte', 'Metrici', 'Istoric'];
export const MANAGER_NAV = [
  'Live',
  'Alerte',
  'Reguli',
  'Dispozitive',
  'Metrici',
  'Istoric',
  'Echipă',
];
export const OWNER_NAV = [...MANAGER_NAV, 'Locații'];
