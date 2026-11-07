import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it } from 'vitest';
import { ApiContext } from '../api/context';
import { MockApi } from '../api/mock';
import { MOCK_INVITE_TOKEN, MOCK_PASSWORD } from '../api/mockAccounts';
import { InvitePage } from '../pages/InvitePage';
import { LoginPage } from '../pages/LoginPage';
import { RegisterPage } from '../pages/RegisterPage';
import { AuthProvider } from './AuthProvider';
import { RequireAuth } from './RequireAuth';
import { passwordStrength, safeNext } from './session';

function renderAt(path: string) {
  const api = new MockApi({ latencyMs: 0, autoplay: false });
  render(
    <ApiContext.Provider value={api}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/intra" element={<LoginPage />} />
            <Route path="/cont-nou" element={<RegisterPage />} />
            <Route path="/invitatie/:token" element={<InvitePage />} />
            <Route element={<RequireAuth />}>
              <Route path="/" element={<h1>Live</h1>} />
              <Route path="/alerte" element={<h1>Alerte</h1>} />
              <Route path="/locatii" element={<h1>Locații</h1>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </ApiContext.Provider>,
  );
  return api;
}

beforeEach(() => localStorage.clear());

describe('auth', () => {
  it('sends a signed-out visitor to the login page', async () => {
    renderAt('/');
    expect(await screen.findByRole('heading', { name: 'Intră în cont' })).toBeVisible();
  });

  it('signs in and returns to the page that was asked for (notification links)', async () => {
    const user = userEvent.setup();
    renderAt('/alerte');
    await user.type(await screen.findByLabelText('Email'), 'staff@aivee.demo');
    await user.type(screen.getByLabelText('Parolă'), MOCK_PASSWORD);
    await user.click(screen.getByRole('button', { name: 'Intră în cont' }));
    expect(await screen.findByRole('heading', { name: 'Alerte' })).toBeVisible();
  });

  it('signs in with one click on a demo role card', async () => {
    const user = userEvent.setup();
    renderAt('/alerte');
    const demo = await screen.findByRole('group', { name: /Încearcă un cont demo/ });
    await user.click(within(demo).getByRole('button', { name: /Manager/ }));
    expect(await screen.findByRole('heading', { name: 'Alerte' })).toBeVisible();
  });

  it('lights the current step and fills it as the form is filled', async () => {
    const user = userEvent.setup();
    renderAt('/cont-nou');
    const progress = await screen.findByRole('progressbar', { name: 'Cont completat' });
    expect(progress).toHaveAttribute('aria-valuenow', '0');
    await user.type(screen.getByLabelText('Numele tău'), 'Ana Pop');
    await user.type(screen.getByLabelText('Email'), 'ana@bistro.ro');
    expect(progress).toHaveAttribute('aria-valuenow', '2');
    expect(progress.closest('li')).toHaveAttribute('aria-current', 'step');
  });

  it('shows the API message for a wrong password', async () => {
    const user = userEvent.setup();
    renderAt('/intra');
    await user.type(await screen.findByLabelText('Email'), 'staff@aivee.demo');
    await user.type(screen.getByLabelText('Parolă'), 'gresit');
    await user.click(screen.getByRole('button', { name: 'Intră în cont' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Email sau parolă greșită.');
  });

  it('rejects an invalid email before calling the API', async () => {
    const user = userEvent.setup();
    renderAt('/intra');
    await user.type(await screen.findByLabelText('Email'), 'ana');
    await user.type(screen.getByLabelText('Parolă'), 'x');
    await user.click(screen.getByRole('button', { name: 'Intră în cont' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Scrie o adresă de email validă.');
  });

  it('registers an owner and continues to creating the first location', async () => {
    const user = userEvent.setup();
    renderAt('/cont-nou');
    await user.type(await screen.findByLabelText('Numele tău'), 'Ana Pop');
    await user.type(screen.getByLabelText('Email'), 'ana@bistro.ro');
    await user.type(screen.getByLabelText('Numele firmei'), 'Bistro Ana SRL');
    await user.type(screen.getByLabelText('Parolă'), 'parola-lunga');
    await user.click(screen.getByRole('checkbox', { name: /Sunt de acord/ }));
    await user.click(screen.getByRole('button', { name: 'Creează contul și continuă' }));
    expect(await screen.findByRole('heading', { name: 'Locații' })).toBeVisible();
  });

  it('asks for an 8-character password and the terms before registering', async () => {
    const user = userEvent.setup();
    renderAt('/cont-nou');
    await user.type(await screen.findByLabelText('Numele tău'), 'Ana');
    await user.type(screen.getByLabelText('Email'), 'ana@bistro.ro');
    await user.type(screen.getByLabelText('Numele firmei'), 'Bistro');
    await user.type(screen.getByLabelText('Parolă'), 'scurt');
    await user.click(screen.getByRole('button', { name: 'Creează contul și continuă' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Parola are nevoie de minim 8 caractere.');
    await user.type(screen.getByLabelText('Parolă'), '-mai-lung');
    await user.click(screen.getByRole('button', { name: 'Creează contul și continuă' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Bifează acordul ca să continui.');
  });

  it('accepts an invite and lands in the app', async () => {
    const user = userEvent.setup();
    renderAt(`/invitatie/${MOCK_INVITE_TOKEN}`);
    expect(
      await screen.findByRole('heading', { name: 'Intră în echipa Terasa demo' }),
    ).toBeVisible();
    await user.type(screen.getByLabelText('Numele tău'), 'Dan Nou');
    await user.type(screen.getByLabelText('Parolă'), 'parola-noua');
    await user.click(screen.getByRole('button', { name: 'Acceptă invitația' }));
    expect(await screen.findByRole('heading', { name: 'Live' })).toBeVisible();
  });

  it('explains an expired or unknown invite', async () => {
    renderAt('/invitatie/nu-exista');
    expect(await screen.findByRole('alert')).toHaveTextContent('Invitația nu mai este valabilă.');
  });
});

describe('session helpers', () => {
  it('scores length and variety from 0 to 4', () => {
    expect(passwordStrength('')).toBe(0);
    expect(passwordStrength('scurt')).toBe(1);
    expect(passwordStrength('parolalunga')).toBe(2);
    expect(passwordStrength('ParolaLunga7')).toBe(3);
    expect(passwordStrength('Parola-Lunga-2026!')).toBe(4);
  });

  it('follows only same-app paths after sign-in', () => {
    expect(safeNext('/alerte?id=1')).toBe('/alerte?id=1');
    expect(safeNext('//evil.example')).toBe('/');
    expect(safeNext('https://evil.example')).toBe('/');
    expect(safeNext(null)).toBe('/');
  });
});
