import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { ApiContext } from './api/context';
import { MockApi } from './api/mock';
import { MOCK_PASSWORD } from './api/mockAccounts';
import { AuthProvider } from './auth/AuthProvider';

function renderApp(path = '/', email: string | null = 'manager@aivee.demo') {
  const api = new MockApi({ latencyMs: 0, autoplay: false });
  if (email) api.accounts.login(email, MOCK_PASSWORD);
  render(
    <ApiContext.Provider value={api}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </ApiContext.Provider>,
  );
  return api;
}

beforeEach(() => localStorage.clear());

describe('App with the mock API', () => {
  it('shows who is signed in and signs out to the login page', async () => {
    const user = userEvent.setup();
    renderApp();
    expect(await screen.findByText('Mihai Ionescu')).toBeInTheDocument();
    expect(screen.getByText(/Manager · manager@aivee.demo/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Ieși din cont' }));
    expect(await screen.findByRole('heading', { name: 'Intră în cont' })).toBeVisible();
  });

  it('hides configuration from staff and keeps them out of it', async () => {
    const rules = vi.spyOn(MockApi.prototype, 'listRules');
    const suggestions = vi.spyOn(MockApi.prototype, 'listSuggestions');
    renderApp('/reguli', 'staff@aivee.demo');
    const nav = await screen.findByRole('navigation', { name: 'Principal' });
    expect(within(nav).getByRole('link', { name: /Alerte/ })).toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: /Reguli/ })).toBeNull();
    expect(within(nav).queryByRole('link', { name: /Echipă/ })).toBeNull();
    expect(await screen.findByRole('heading', { name: 'Live' })).toBeVisible();
    // The API answers 403 to staff on every /api/rules* call, so the UI never asks.
    expect(rules).not.toHaveBeenCalled();
    // Suggestions are staff.review only; a 403 there used to blank the whole live data load.
    expect(suggestions).not.toHaveBeenCalled();
    rules.mockRestore();
    suggestions.mockRestore();
  });

  it('lets the owner switch between locations', async () => {
    const user = userEvent.setup();
    renderApp('/', 'owner@aivee.demo');
    const select = await screen.findByRole('combobox', { name: 'Locația' });
    expect(
      within(select)
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['Terasa demo', 'Bistro Centru']);
    await user.selectOptions(select, 'centru');
    expect(localStorage.getItem('aivee.location')).toBe('centru');
    const nav = screen.getByRole('navigation', { name: 'Principal' });
    expect(within(nav).getByRole('link', { name: /Locații/ })).toBeInTheDocument();
  });

  it('takes an open alert with "Merg eu" and shows the timeline', async () => {
    const user = userEvent.setup();
    const api = new MockApi({ latencyMs: 0, autoplay: false });
    api.emitAlert('r-neservit', 'z-masa-2', 'opened', 'Masa 2: nimeni de la personal de 1 minut');
    api.accounts.login('staff@aivee.demo', MOCK_PASSWORD);
    render(
      <ApiContext.Provider value={api}>
        <AuthProvider>
          <MemoryRouter initialEntries={['/alerte']}>
            <App />
          </MemoryRouter>
        </AuthProvider>
      </ApiContext.Provider>,
    );
    await user.click(await screen.findByRole('button', { name: 'Merg eu la Masa 2' }));
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Merg eu la Masa 2' })).toBeNull(),
    );
    // Taken now by Ana, plus the seeded alert she took earlier.
    expect(screen.getAllByText(/· Ana Dumitru/)).toHaveLength(2);
    // The seeded closed alert shows its full lifecycle with durations.
    expect(screen.getAllByText(/reacție 30 s/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/drum 1 min 18 s/).length).toBeGreaterThan(0);
  });

  it('filters the history by kind', async () => {
    const user = userEvent.setup();
    renderApp('/istoric');
    expect(await screen.findByText(/a confirmat că #7 e din personal/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Tip'), 'rule');
    expect(await screen.findByText(/a schimbat regula „Masă neservită”/)).toBeInTheDocument();
    expect(screen.queryByText(/a confirmat că #7/)).toBeNull();
  });

  it('creates an invite link for a new staff member', async () => {
    const user = userEvent.setup();
    renderApp('/echipa');
    expect(await screen.findByText('Ana Dumitru')).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: 'Manager' })).toBeNull();
    await user.type(screen.getByLabelText('Email'), 'nou@restaurant.ro');
    await user.click(screen.getByRole('button', { name: 'Creează linkul de invitație' }));
    const link = (await screen.findByLabelText('Link de invitație')) as HTMLInputElement;
    expect(link.value).toContain('/invitatie/');
  });

  it('shows cameras, the offline device and recent alerts on the live page', async () => {
    renderApp();
    expect(await screen.findByRole('article', { name: 'Camera Sala principală' })).toBeVisible();
    const terrace = screen.getByRole('article', { name: 'Camera Terasă' });
    expect(within(terrace).getByText('Dispozitiv offline')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Alerte recente' })).toBeInTheDocument();
    expect(await screen.findAllByText('Închisă', { selector: '.pill' })).toHaveLength(2);
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
