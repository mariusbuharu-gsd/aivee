import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it } from 'vitest';
import { LoginPage } from '../pages/LoginPage';
import { RegisterPage } from '../pages/RegisterPage';
import { AuthProvider } from './AuthProvider';
import { RequireAuth } from './RequireAuth';
import { passwordStrength, SESSION_KEY } from './session';

function renderAt(path: string) {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/intra" element={<LoginPage />} />
          <Route path="/cont-nou" element={<RegisterPage />} />
          <Route element={<RequireAuth />}>
            <Route path="/" element={<h1>Live</h1>} />
            <Route path="/dispozitive" element={<h1>Dispozitive</h1>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe('auth', () => {
  it('sends a signed-out visitor to the login page', () => {
    renderAt('/');
    expect(screen.getByRole('heading', { name: 'Intră în cont' })).toBeVisible();
  });

  it('signs in and returns to the page that was asked for', async () => {
    const user = userEvent.setup();
    renderAt('/dispozitive');
    await user.type(screen.getByLabelText('Email'), 'ana@restaurant.ro');
    await user.type(screen.getByLabelText('Parolă'), 'parola-demo');
    await user.click(screen.getByRole('button', { name: 'Intră în cont' }));
    expect(await screen.findByRole('heading', { name: 'Dispozitive' })).toBeVisible();
    expect(localStorage.getItem(SESSION_KEY)).toContain('ana@restaurant.ro');
  });

  it('keeps the session only for this tab when "remember me" is off', async () => {
    const user = userEvent.setup();
    renderAt('/intra');
    await user.type(screen.getByLabelText('Email'), 'ana@restaurant.ro');
    await user.type(screen.getByLabelText('Parolă'), 'parola-demo');
    await user.click(screen.getByLabelText('Ține-mă minte pe acest dispozitiv'));
    await user.click(screen.getByRole('button', { name: 'Intră în cont' }));
    expect(await screen.findByRole('heading', { name: 'Live' })).toBeVisible();
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
    expect(sessionStorage.getItem(SESSION_KEY)).toContain('ana@restaurant.ro');
  });

  it('rejects an invalid email with a Romanian message', async () => {
    const user = userEvent.setup();
    renderAt('/intra');
    await user.type(screen.getByLabelText('Email'), 'ana');
    await user.type(screen.getByLabelText('Parolă'), 'x');
    await user.click(screen.getByRole('button', { name: 'Intră în cont' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Scrie o adresă de email validă.');
  });

  it('registers an owner and continues to adding a device', async () => {
    const user = userEvent.setup();
    renderAt('/cont-nou');
    await user.type(screen.getByLabelText('Numele tău'), 'Ana Pop');
    await user.type(screen.getByLabelText('Email'), 'ana@restaurant.ro');
    await user.type(screen.getByLabelText('Numele locației'), 'Bistro Ana');
    await user.click(screen.getByLabelText('Terasă / bar'));
    await user.type(screen.getByLabelText('Parolă'), 'o-parola-lunga');
    await user.click(screen.getByRole('checkbox', { name: /Sunt de acord/ }));
    await user.click(screen.getByRole('button', { name: 'Creează contul și continuă' }));
    expect(await screen.findByRole('heading', { name: 'Dispozitive' })).toBeVisible();
    const saved = JSON.parse(localStorage.getItem(SESSION_KEY) ?? '{}');
    expect(saved).toMatchObject({ name: 'Ana Pop', venue: 'Bistro Ana', venueType: 'bar' });
  });

  it('asks for a 10-character password and the terms before registering', async () => {
    const user = userEvent.setup();
    renderAt('/cont-nou');
    await user.type(screen.getByLabelText('Numele tău'), 'Ana');
    await user.type(screen.getByLabelText('Email'), 'ana@restaurant.ro');
    await user.type(screen.getByLabelText('Numele locației'), 'Bistro');
    await user.type(screen.getByLabelText('Parolă'), 'scurta');
    await user.click(screen.getByRole('button', { name: 'Creează contul și continuă' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Parola are nevoie de minim 10 caractere.');
    await user.type(screen.getByLabelText('Parolă'), '-mai-lunga');
    await user.click(screen.getByRole('button', { name: 'Creează contul și continuă' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Bifează acordul ca să continui.');
  });
});

describe('passwordStrength', () => {
  it('scores length and variety from 0 to 4', () => {
    expect(passwordStrength('')).toBe(0);
    expect(passwordStrength('scurta')).toBe(1);
    expect(passwordStrength('parolalunga')).toBe(2);
    expect(passwordStrength('ParolaLunga7')).toBe(3);
    expect(passwordStrength('Parola-Lunga-2026!')).toBe(4);
  });
});
