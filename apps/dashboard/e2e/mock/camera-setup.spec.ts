import { expect, test, type Page } from '@playwright/test';
import { MOCK_PASSWORD, signIn } from '../helpers';

// "Adaugă cameră" for an owner who knows nothing about cameras: the AiVee box looks for them
// on the venue network. The mock's box finds two Tapo cameras and a Hikvision; the Tapo at
// 192.168.1.20 is "Sala principală" already. The password "gresit" is always refused.

async function openWizard(page: Page) {
  await signIn(page, 'owner', MOCK_PASSWORD, '/dispozitive');
  await page.getByRole('button', { name: 'Adaugă cameră' }).first().click();
  return page.getByRole('dialog', { name: 'Adaugă o cameră' });
}

test('discover, pick, test, name and save a camera, then draw its zones', async ({ page }) => {
  const secret = 'Cont-Camera-7';
  const dialog = await openWizard(page);

  // One online box: it is picked by itself.
  await dialog.getByRole('button', { name: 'Caută camere' }).click();
  await expect(dialog.getByRole('progressbar', { name: 'Caut camere' })).toBeVisible();
  const found = dialog.getByRole('list', { name: 'Camere găsite' });
  await expect(found.getByRole('listitem')).toHaveCount(3);
  const taken = found.getByRole('button', { name: /Tapo C200/ });
  await expect(taken).toBeDisabled();
  await expect(taken).toContainText('Deja adăugată');

  await found.getByRole('button', { name: /Tapo C210/ }).click();
  await expect(dialog.getByText('Tapo cere contul camerei', { exact: false })).toBeVisible();
  await dialog.getByLabel('Utilizator').fill('ana');
  await dialog.getByLabel('Parolă', { exact: true }).fill(secret);
  await dialog.getByRole('button', { name: 'Testează' }).click();
  await expect(dialog.getByRole('img', { name: /Imagine de test/ })).toBeVisible();
  await expect(dialog.getByText('Camera răspunde. Așa o vede AiVee.')).toBeVisible();

  await dialog.getByRole('button', { name: 'Continuă' }).click();
  await dialog.getByRole('button', { name: 'Bar', exact: true }).click();
  await expect(dialog.getByLabel('Numele camerei')).toHaveValue('Bar');
  // Nothing technical on the owner's way: no address, id, box or password.
  for (const text of ['rtsp://', 'mqtt-frames://', 'edge-sala', 'cam-', secret]) {
    await expect(dialog).not.toContainText(text);
  }
  await dialog.getByRole('button', { name: 'Salvează camera' }).click();

  await expect(page.getByRole('heading', { name: /Zone · Bar/ })).toBeVisible();
  await expect(page.locator('body')).not.toContainText(secret);

  // Back on Camere the new camera is there, and a second scan shows it as added.
  await page.getByRole('link', { name: 'Gata' }).click();
  await expect(page.getByRole('listitem', { name: 'Camera Bar' })).toBeVisible();
  await page.getByRole('button', { name: 'Adaugă cameră' }).first().click();
  await dialog.getByRole('button', { name: 'Caută camere' }).click();
  await expect(found.getByRole('button', { name: /Tapo C210/ })).toBeDisabled();
});

test('a refused Tapo password points to the camera-account guide', async ({ page }) => {
  const dialog = await openWizard(page);
  await dialog.getByRole('button', { name: 'Caută camere' }).click();
  await dialog
    .getByRole('list', { name: 'Camere găsite' })
    .getByRole('button', { name: /Tapo C210/ })
    .click();
  const guide = dialog.locator('details', { hasText: 'Cum faci contul camerei' });
  await expect(guide).not.toHaveAttribute('open');

  await dialog.getByLabel('Utilizator').fill('contul-meu-tapo@example.com');
  await dialog.getByLabel('Parolă', { exact: true }).fill('gresit');
  await dialog.getByRole('button', { name: 'Testează' }).click();
  const problem = dialog.getByRole('alert');
  await expect(problem).toContainText('a refuzat utilizatorul sau parola');
  await expect(problem).toContainText('nu contul tău Tapo');
  await expect(guide).toHaveAttribute('open');
  await expect(guide.getByText(/Setări avansate/)).toBeVisible();
  await expect(guide.getByText(/Third-Party Compatibility/)).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Continuă' })).toHaveCount(0);

  // The saved camera's card can be tested too, by id: the password is never sent again.
  await dialog.getByRole('button', { name: 'Înapoi' }).click();
  await page.keyboard.press('Escape');
  const sala = page.getByRole('listitem', { name: 'Camera Sala principală' });
  await sala.getByRole('button', { name: 'Testează' }).click();
  const check = page.getByRole('dialog', { name: 'Testează „Sala principală”' });
  await expect(check.getByText('Camera răspunde. Așa o vede AiVee.')).toBeVisible();
});

test('with the box switched off, the owner is told what to check', async ({ page }) => {
  // Bistro Centru's box is off in the mock.
  await page.addInitScript(() => localStorage.setItem('aivee.location', 'centru'));
  const dialog = await openWizard(page);
  await expect(
    dialog.getByRole('heading', { name: 'Cutia AiVee nu e pornită sau nu e conectată' }),
  ).toBeVisible();
  await expect(dialog.getByText(/în priză și are lumina aprinsă/)).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Caută camere' })).toHaveCount(0);
  await dialog.getByRole('button', { name: 'Verifică din nou' }).click();
  await expect(
    dialog.getByRole('heading', { name: 'Cutia AiVee nu e pornită sau nu e conectată' }),
  ).toBeVisible();
  await expect(dialog).not.toContainText('edge-centru');
});
