import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { App } from './App';
import { ApiContext } from './api/context';
import { AuthProvider } from './auth/AuthProvider';
import { saveSession } from './auth/session';
import { MockApi } from './api/mock';
import { LiveDataProvider } from './state/LiveData';

function renderApp(path = '/') {
  const api = new MockApi({ latencyMs: 0, autoplay: false });
  saveSession({
    name: 'Ana',
    email: 'ana@restaurant.ro',
    venue: 'Bistro Ana',
    venueType: 'restaurant',
  });
  render(
    <ApiContext.Provider value={api}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <LiveDataProvider>
            <App />
          </LiveDataProvider>
        </MemoryRouter>
      </AuthProvider>
    </ApiContext.Provider>,
  );
  return api;
}

describe('App with the mock API', () => {
  it('shows the venue in the sidebar and signs out to the login page', async () => {
    const user = userEvent.setup();
    renderApp();
    expect(await screen.findByText('Bistro Ana')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Ieși din cont' }));
    expect(screen.getByRole('heading', { name: 'Intră în cont' })).toBeVisible();
  });

  it('shows cameras, the offline device and recent alerts on the live page', async () => {
    renderApp();
    expect(await screen.findByRole('article', { name: 'Camera Sala principală' })).toBeVisible();
    const terrace = screen.getByRole('article', { name: 'Camera Terasă' });
    expect(within(terrace).getByText('Dispozitiv offline')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Alerte recente' })).toBeInTheDocument();
    expect(await screen.findAllByText('Închisă')).toHaveLength(2);
    expect((await screen.findAllByText(/angajat #7/)).length).toBeGreaterThan(0);
  });

  it('navigates to the zone editor and lists the camera zones', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(
      await screen.findByRole('link', { name: 'Editează zonele pentru Sala principală' }),
    );
    expect(await screen.findByRole('heading', { name: /Zone \(3\)/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Masa 2/ }));
    expect(screen.getByLabelText('Nume')).toHaveValue('Masa 2');
    await user.click(screen.getByRole('button', { name: /Șterge/ }));
    expect(screen.getByRole('heading', { name: /Zone \(2\)/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Salvează zonele' })).toBeEnabled();
  });

  it('adds a camera, then drafts and confirms a rule in mock mode', async () => {
    const user = userEvent.setup();
    renderApp('/dispozitive');
    await screen.findByRole('heading', { name: 'Sala principală' });
    expect(screen.getByLabelText('Id cameră')).toHaveValue('cam-01');
    await user.type(screen.getByLabelText('Nume'), 'Bar');
    await user.type(screen.getByLabelText(/Adresa sursei/), 'rtsp://bar/1');
    await user.click(screen.getByRole('button', { name: 'Adaugă camera' }));
    expect(await screen.findByRole('heading', { name: /Zone · Bar/ })).toBeInTheDocument();
    expect(screen.getByLabelText('Încarcă o imagine din cameră')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Reguli' }));
    await user.type(
      await screen.findByLabelText('Spune-i camerei ce să vadă'),
      'Anunță-mă dacă la o masă nu vine nimeni de 1 minut',
    );
    await user.click(screen.getByRole('button', { name: 'Creează regula' }));
    const panel = await screen.findByRole('region', { name: 'Ce am înțeles' });
    const before = screen.getAllByRole('heading', { level: 3 }).length;
    await user.click(within(panel).getByRole('button', { name: /Confirmă și salvează/ }));
    expect(await screen.findByText(/a fost salvată și trimisă/)).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 3 }).length).toBe(before);
  });
});
