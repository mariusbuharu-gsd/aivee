import { expect, test } from '@playwright/test';
import { MOCK_PASSWORD, choose, signIn } from '../helpers';

// The mock location has two cameras: "Sala principală" (online) and "Terasă" (its device is
// offline). Production pilots run two IP cameras on one location.

test('Live shows both cameras by name, the offline one as one clear row', async ({ page }) => {
  await signIn(page, 'manager', MOCK_PASSWORD);
  const cameras = page.getByRole('region', { name: 'Camere' });
  const sala = cameras.getByRole('article', { name: 'Camera Sala principală' });
  const terasa = cameras.getByRole('article', { name: 'Camera Terasă' });
  await expect(sala).toBeVisible();
  await expect(sala.getByText('LIVE')).toBeVisible();
  await expect(terasa.getByText('Cameră offline')).toBeVisible();
  await expect(terasa).toContainText('Dispozitivul AiVee din local nu răspunde.');
  // No raw device ids in sight.
  await expect(page.locator('main')).not.toContainText('edge-terasa');
});

test('staff get no live video, only alert cards', async ({ page }) => {
  await signIn(page, 'staff', MOCK_PASSWORD);
  await expect(page.getByRole('heading', { name: 'Live', level: 1 })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Alerte' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Camere' })).toHaveCount(0);
  await expect(page.locator('video, .tile-media')).toHaveCount(0);
});

test('the zone editor switches between the two cameras', async ({ page }) => {
  await signIn(page, 'manager', MOCK_PASSWORD, '/camere/cam-sala/zone');
  const pick = page.getByRole('group', { name: 'Camera' });
  await expect(pick.getByRole('button', { name: 'Sala principală' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByRole('heading', { name: '3 zone' })).toBeVisible();
  await pick.getByRole('button', { name: 'Terasă · offline' }).click();
  await expect(page).toHaveURL(/\/camere\/cam-terasa\/zone$/);
  await expect(page.getByRole('heading', { name: /Zone · Terasă/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: '1 zonă' })).toBeVisible();
  await expect(page.getByAltText(/Ultima captură de la Terasă/)).toBeVisible();
});

test('an owner adds a Tapo camera by IP, user and password, and tests it', async ({ page }) => {
  const secret = 'Parola-Tapo-42';
  await signIn(page, 'owner', MOCK_PASSWORD, '/dispozitive');
  await page.getByRole('button', { name: 'Adaugă cameră' }).first().click();
  const dialog = page.getByRole('dialog', { name: 'Adaugă o cameră' });
  await expect(dialog.getByRole('button', { name: 'Cameră IP' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(dialog.getByRole('combobox', { name: 'Marca' })).toContainText('Tapo');
  await dialog.getByLabel('Nume').fill('Bar');
  await dialog.getByLabel('Adresa IP').fill('192.168.1.31');
  await dialog.getByLabel('Utilizator').fill('ana');

  // A wrong password: the camera says so, in Romanian.
  await dialog.getByLabel('Parolă', { exact: true }).fill('gresit');
  await dialog.getByRole('button', { name: 'Testează camera' }).click();
  await expect(dialog.getByText(/a refuzat utilizatorul sau parola/)).toBeVisible();

  await dialog.getByLabel('Parolă', { exact: true }).fill(secret);
  await dialog.getByRole('button', { name: 'Testează camera' }).click();
  await expect(dialog.getByText('Camera răspunde. Așa o vede AiVee.')).toBeVisible();
  await dialog.getByText('Avansat, pentru instalator').click();
  await expect(dialog.getByText('rtsp://ana:••••@192.168.1.31:554/stream2')).toBeVisible();
  await expect(page.locator('body')).not.toContainText(secret);

  await dialog.getByRole('button', { name: 'Adaugă camera' }).click();
  await expect(page.getByRole('heading', { name: /Zone · Bar/ })).toBeVisible();
  await expect(page.locator('body')).not.toContainText(secret);

  // Back on Camere (in-app: a reload would reset the in-browser mock), the card never shows
  // the password either.
  await page.getByRole('link', { name: 'Gata' }).click();
  const card = page.getByRole('listitem', { name: 'Camera Bar' });
  await expect(card).toBeVisible();
  await card.getByText('Detalii tehnice').click();
  await expect(card).toContainText('rtsp://••••@192.168.1.31/…');
  await expect(page.locator('body')).not.toContainText(secret);
});

test('a Hikvision camera gets its substream path', async ({ page }) => {
  await signIn(page, 'owner', MOCK_PASSWORD, '/dispozitive');
  await page.getByRole('button', { name: 'Adaugă cameră' }).first().click();
  const dialog = page.getByRole('dialog', { name: 'Adaugă o cameră' });
  await choose(page, 'Marca', 'Hikvision');
  await expect(dialog.getByLabel('Utilizator')).toHaveValue('admin');
  await dialog.getByLabel('Adresa IP').fill('10.0.0.8');
  await dialog.getByLabel('Parolă', { exact: true }).fill('x');
  await dialog.getByText('Avansat, pentru instalator').click();
  await expect(
    dialog.getByText('rtsp://admin:••••@10.0.0.8:554/Streaming/Channels/102'),
  ).toBeVisible();
  // An address with a scheme is refused before anything is sent.
  await dialog.getByLabel('Adresa IP').fill('rtsp://10.0.0.8');
  await dialog.getByLabel('Nume').fill('Hol');
  await dialog.getByRole('button', { name: 'Adaugă camera' }).click();
  await expect(dialog.getByText(/Scrie doar adresa IP/)).toBeVisible();
});
