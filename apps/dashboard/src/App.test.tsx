import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { ApiContext } from './api/context';
import { MockApi } from './api/mock';
import { MOCK_PASSWORD } from './api/mockAccounts';
import { AuthProvider } from './auth/AuthProvider';
import { Toaster } from './ui/Toaster';

function renderApp(path = '/', email: string | null = 'manager@aivee.demo') {
  const api = new MockApi({ latencyMs: 0, autoplay: false });
  if (email) api.accounts.login(email, MOCK_PASSWORD);
  render(
    <ApiContext.Provider value={api}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <Toaster>
            <App />
          </Toaster>
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
    expect(select).toHaveTextContent('Terasa demo');
    await user.click(select);
    const options = within(screen.getByRole('listbox')).getAllByRole('option');
    expect(options.map((o) => o.textContent)).toEqual([
      'Terasa demoRestaurant · Proprietar',
      'Bistro CentruRestaurant · Proprietar',
    ]);
    await user.click(screen.getByRole('option', { name: /Bistro Centru/ }));
    expect(localStorage.getItem('aivee.location')).toBe('centru');
    expect(await screen.findByText('Acum vezi Bistro Centru')).toBeInTheDocument();
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
    // Taken now by Ana (timeline), plus the seeded alert she took earlier (summary + timeline).
    expect(screen.getAllByText(/· Ana Dumitru/)).toHaveLength(3);
    expect(screen.getByText(/a durat .* · Ana Dumitru/)).toBeInTheDocument();
    // The seeded closed alert shows its full lifecycle with durations.
    expect(screen.getAllByText(/reacție 30 s/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/drum 1 min 18 s/).length).toBeGreaterThan(0);
  });

  it('filters the history by kind', async () => {
    const user = userEvent.setup();
    renderApp('/istoric');
    expect(await screen.findByText(/a confirmat că #7 e din personal/)).toBeInTheDocument();
    await user.click(screen.getByRole('combobox', { name: 'Tip' }));
    await user.click(screen.getByRole('option', { name: 'Reguli' }));
    expect(await screen.findByText(/a schimbat regula „Masă neservită”/)).toBeInTheDocument();
    expect(screen.queryByText(/a confirmat că #7/)).toBeNull();
    // The change reads in words; the active filter shows as a removable chip.
    expect(screen.getAllByText(/→/).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: 'Șterge filtrele' }));
    expect(await screen.findByText(/a confirmat că #7 e din personal/)).toBeInTheDocument();
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

  it('changes a role with undo, removes through a dialog and revokes an invite', async () => {
    const user = userEvent.setup();
    renderApp('/echipa', 'owner@aivee.demo');
    const role = await screen.findByRole('combobox', { name: 'Rol pentru Ana Dumitru' });
    await user.click(role);
    await user.click(screen.getByRole('option', { name: /Manager/ }));
    expect(await screen.findByText('Ana Dumitru e acum Manager')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Anulează' }));
    await waitFor(() => expect(role).toHaveTextContent('Personal'));

    await user.click(screen.getByRole('button', { name: 'Acțiuni pentru Ana Dumitru' }));
    await user.click(screen.getByRole('menuitem', { name: 'Scoate din echipă…' }));
    const dialog = screen.getByRole('dialog', { name: /Scoți din echipa .*: Ana Dumitru/ });
    await user.click(within(dialog).getByRole('button', { name: 'Scoate din echipă' }));
    await waitFor(() => expect(screen.queryByText('staff@aivee.demo')).toBeNull());

    expect(screen.getByRole('heading', { name: 'În așteptare' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retrage' }));
    await user.click(screen.getByRole('button', { name: 'Retrage invitația' }));
    expect(await screen.findByText('Invitația a fost retrasă')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'În așteptare' })).toBeNull();
  });

  it('deletes a location only after its name is typed', async () => {
    const user = userEvent.setup();
    renderApp('/locatii', 'owner@aivee.demo');
    await user.click(await screen.findByRole('button', { name: 'Acțiuni pentru Bistro Centru' }));
    await user.click(screen.getByRole('menuitem', { name: 'Șterge locația…' }));
    const dialog = screen.getByRole('dialog', { name: /Ștergi definitiv locația „Bistro Centru”/ });
    const go = within(dialog).getByRole('button', { name: 'Șterge locația' });
    expect(go).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/ca să confirmi/), 'Bistro Centru');
    await user.click(go);
    expect(await screen.findByText('Locația „Bistro Centru” a fost ștearsă')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Acțiuni pentru Bistro Centru' })).toBeNull(),
    );
  });

  it('undoes a zone delete from the toast and asks before leaving unsaved zones', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(
      await screen.findByRole('link', { name: 'Editează zonele pentru Sala principală' }),
    );
    await user.click(await screen.findByRole('button', { name: /Masa 2/ }));
    await user.click(screen.getByRole('button', { name: /Șterge/ }));
    expect(screen.getByRole('heading', { name: /Zone \(2\)/ })).toBeInTheDocument();
    expect(screen.getByText('modificări nesalvate')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Anulează' }));
    expect(screen.getByRole('heading', { name: /Zone \(3\)/ })).toBeInTheDocument();

    const nav = screen.getByRole('navigation', { name: 'Principal' });
    await user.click(within(nav).getByRole('link', { name: /Alerte/ }));
    const dialog = screen.getByRole('dialog', { name: /modificări nesalvate/ });
    await user.click(within(dialog).getByRole('button', { name: 'Rămâi' }));
    expect(screen.getByRole('heading', { name: /Zone · Sala principală/ })).toBeInTheDocument();
    await user.click(within(nav).getByRole('link', { name: /Alerte/ }));
    await user.click(screen.getByRole('button', { name: 'Salvează și pleacă' }));
    expect(await screen.findByRole('heading', { name: 'Alerte', level: 1 })).toBeInTheDocument();
    expect(screen.getByText('3 zone salvate')).toBeInTheDocument();
  });

  it('adds a camera, then drafts and confirms a rule in mock mode', async () => {
    const user = userEvent.setup();
    renderApp('/dispozitive');
    await screen.findByRole('heading', { name: 'Sala principală' });
    await user.click(screen.getByRole('button', { name: 'Adaugă cameră' }));
    expect(screen.getByLabelText('Id cameră')).toHaveValue('cam-01');
    await user.type(screen.getByLabelText('Nume'), 'Bar');
    await user.type(screen.getByLabelText(/Adresa sursei/), 'rtsp://bar/1');
    await user.click(screen.getByRole('button', { name: 'Adaugă camera' }));
    expect(await screen.findByRole('heading', { name: /Zone · Bar/ })).toBeInTheDocument();
    expect(screen.getByText('Camera „Bar” a fost adăugată')).toBeInTheDocument();
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
    expect(await screen.findByText(/a fost salvată și pornită/)).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 3 }).length).toBe(before);
  });
});
