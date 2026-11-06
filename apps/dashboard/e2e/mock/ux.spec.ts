import { expect, test } from '@playwright/test';
import { MOCK_PASSWORD, choose, signIn } from '../helpers';

// The UX rules from the review: no native selects or browser dialogs, confirmations before
// losing data, a toast after every action.

const OWNER_PAGES = [
  '/',
  '/alerte',
  '/reguli',
  '/dispozitive',
  '/metrici',
  '/istoric',
  '/echipa',
  '/locatii',
];

test('no page uses a native select or a browser dialog', async ({ page }) => {
  page.on('dialog', (d) => {
    throw new Error(`browser dialog: ${d.message()}`);
  });
  await signIn(page, 'owner', MOCK_PASSWORD);
  for (const path of OWNER_PAGES) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.locator('select')).toHaveCount(0);
  }
  await page.goto('/camere/cam-sala/zone');
  await expect(page.locator('select')).toHaveCount(0);
});

test('a rule pauses with undo and deletes only after the dialog', async ({ page }) => {
  await signIn(page, 'manager', MOCK_PASSWORD, '/reguli');
  const card = page.locator('.rule-card').first();
  const name = (await card.getByRole('heading', { level: 3 }).textContent()) ?? '';
  await card.getByRole('switch').click();
  await expect(page.getByText(`„${name}” e oprită`)).toBeVisible();
  await page
    .getByRole('region', { name: 'Notificări' })
    .getByRole('button', { name: 'Anulează' })
    .click();
  await expect(card.getByRole('switch')).toBeChecked();

  await card.getByRole('button', { name: /Acțiuni pentru regula/ }).click();
  await page.getByRole('menuitem', { name: 'Șterge regula…' }).click();
  const dialog = page.getByRole('dialog', { name: `Ștergi regula „${name}”?` });
  await expect(dialog.getByRole('button', { name: 'Renunță' })).toBeFocused();
  await dialog.getByRole('button', { name: 'Șterge regula' }).click();
  await expect(page.getByText(`Regula „${name}” a fost ștearsă`)).toBeVisible();
  await expect(page.getByRole('heading', { name, level: 3 })).toHaveCount(0);
});

test('a deleted zone comes back from the toast, and leaving asks first', async ({ page }) => {
  await signIn(page, 'manager', MOCK_PASSWORD, '/camere/cam-sala/zone');
  await page.getByRole('button', { name: /Masa 2/ }).click();
  await page.getByRole('button', { name: /Șterge/ }).click();
  await expect(page.getByRole('heading', { name: /Zone \(2\)/ })).toBeVisible();
  await page
    .getByRole('region', { name: 'Notificări' })
    .getByRole('button', { name: 'Anulează' })
    .click();
  await expect(page.getByRole('heading', { name: /Zone \(3\)/ })).toBeVisible();
  await expect(page.getByText('modificări nesalvate')).toBeVisible();

  await page
    .getByRole('navigation', { name: 'Principal' })
    .getByRole('link', { name: /Alerte/ })
    .click();
  const dialog = page.getByRole('dialog', { name: /modificări nesalvate/ });
  await dialog.getByRole('button', { name: 'Rămâi' }).click();
  await expect(page).toHaveURL(/\/zone$/);
});

test('the history filters through our selects and clears with one click', async ({ page }) => {
  await signIn(page, 'owner', MOCK_PASSWORD, '/istoric');
  await choose(page, 'Cine', /Ana Dumitru/);
  await expect(page.getByRole('button', { name: 'Șterge filtrele' })).toBeVisible();
  await page.getByRole('button', { name: 'Șterge filtrele' }).click();
  await expect(page.getByRole('combobox', { name: 'Cine' })).toContainText('Oricine');
});

test('phones get a bottom bar with the account under "Mai mult"', async ({ page }, info) => {
  test.skip(info.project.name !== 'phone', 'phone layout only');
  await signIn(page, 'staff', MOCK_PASSWORD);
  const bar = page.getByRole('navigation', { name: 'Principal' });
  const box = await bar.boundingBox();
  const viewport = page.viewportSize();
  expect(box && viewport && box.y + box.height).toBeGreaterThan((viewport?.height ?? 0) - 2);
  await bar.getByRole('button', { name: 'Mai mult' }).click();
  await expect(page.getByRole('dialog', { name: 'Mai mult' })).toContainText('Ana Dumitru');
});
