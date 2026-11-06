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
  await expect(page.getByRole('navigation', { name: 'Principal' })).toBeVisible({
    timeout: 20_000,
  });
}

/** On phones the account and the extra links sit under "Mai mult" in the bottom bar. */
export async function openMore(page: Page) {
  const more = page.getByRole('button', { name: 'Mai mult' });
  if (await more.isVisible()) await more.click();
}

export async function signOut(page: Page) {
  await openMore(page);
  await page.getByRole('button', { name: 'Ieși din cont' }).click();
}

/** Pick an option in one of our Selects (a combobox button + listbox). */
export async function choose(page: Page, label: string | RegExp, option: string | RegExp) {
  await page.getByRole('combobox', { name: label }).click();
  await page.getByRole('option', { name: option }).click();
}

/** Link texts in the main navigation, without the alert counter badge. */
export async function navLinks(page: Page): Promise<string[]> {
  const nav = page.getByRole('navigation', { name: 'Principal' });
  await expect(nav.getByRole('link').first()).toBeVisible();
  await openMore(page);
  const texts = (await nav.getByRole('link').allTextContents()).map((t) =>
    t.replace(/\d+$/, '').trim(),
  );
  if (await page.getByRole('dialog', { name: 'Mai mult' }).isVisible()) {
    await page.keyboard.press('Escape');
  }
  return texts;
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
