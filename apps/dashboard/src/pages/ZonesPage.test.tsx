import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { ApiContext } from '../api/context';
import { MockApi } from '../api/mock';
import { MOCK_PASSWORD } from '../api/mockAccounts';
import { AuthProvider } from '../auth/AuthProvider';
import { Toaster } from '../ui/Toaster';

function renderApp(path = '/camere/cam-sala/zone') {
  const api = new MockApi({ latencyMs: 0, autoplay: false });
  api.accounts.login('manager@aivee.demo', MOCK_PASSWORD);
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
afterEach(() => vi.restoreAllMocks());

describe('ZonesPage', () => {
  it('draws from the toolbar on the image, one tool per zone kind', async () => {
    const user = userEvent.setup();
    renderApp();
    const tools = await screen.findByRole(
      'toolbar',
      { name: 'Unelte de desen' },
      { timeout: 5000 },
    );
    for (const label of ['Masă', 'Intrare', 'Zonă angajați']) {
      expect(within(tools).getByRole('button', { name: label })).toHaveAttribute(
        'aria-pressed',
        'false',
      );
    }
    expect(within(tools).queryByRole('button', { name: 'Anulează punctul' })).toBeNull();

    await user.click(within(tools).getByRole('button', { name: 'Intrare' }));
    expect(within(tools).getByRole('button', { name: 'Intrare' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    // The demo camera already has an entrance, so the next one is numbered.
    expect(screen.getByLabelText('Nume')).toHaveValue('Intrare 2');
    expect(within(tools).getByRole('button', { name: 'Anulează punctul' })).toBeDisabled();

    await user.click(within(tools).getByRole('button', { name: 'Masă' }));
    expect(screen.getByLabelText('Nume')).toHaveValue('Masa 3');
    await user.click(within(tools).getByRole('button', { name: 'Renunță' }));
    expect(screen.queryByRole('heading', { name: 'Zonă nouă' })).toBeNull();
  });

  it('offers a capture from one line on the image and lists zones by colour and name', async () => {
    const user = userEvent.setup();
    renderApp();
    const line = await screen.findByText(/Ultima captură a camerei/, undefined, { timeout: 5000 });
    expect(line).toHaveTextContent(/^Ultima captură a camerei, de acum \d+ s · Încarcă o captură$/);
    expect(screen.getByAltText(/Ultima captură de la Sala principală/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Fundal' })).toBeNull();

    const list = screen.getByRole('heading', { name: '3 zone' }).nextElementSibling as HTMLElement;
    const row = within(list).getByRole('button', { name: /Masa 1/ });
    expect(row).not.toHaveTextContent('puncte');
    expect(within(row).getByRole('img', { name: 'Masă' })).toBeInTheDocument();

    const file = new File(['x'], 'sala.png', { type: 'image/png' });
    await user.upload(screen.getByLabelText('Încarcă o imagine din cameră'), file);
    expect(await screen.findByText(/Captură încărcată/)).toHaveTextContent(
      'Captură încărcată · Schimbă',
    );
  });

  it('switches from a capture back to the live frame when the camera is online', async () => {
    const user = userEvent.setup();
    renderApp();
    await screen.findByText(/Ultima captură a camerei/, undefined, { timeout: 5000 });
    expect(screen.queryByRole('button', { name: 'Folosește imaginea live' })).toBeNull();

    const file = new File(['x'], 'sala.png', { type: 'image/png' });
    await user.upload(screen.getByLabelText('Încarcă o imagine din cameră'), file);
    expect(await screen.findByText(/Captură încărcată/)).toHaveTextContent(
      'Captură încărcată · Schimbă · Folosește imaginea live',
    );
    expect(screen.getByAltText(/Imagine încărcată/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Folosește imaginea live' }));
    expect(screen.queryByAltText(/Imagine încărcată/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Folosește imaginea live' })).toBeNull();
    expect(await screen.findByText(/Ultima captură a camerei/)).toHaveTextContent(
      /Ultima captură a camerei.* · Încarcă o captură/,
    );
  });

  it('offers no live frame for an offline camera', async () => {
    const user = userEvent.setup();
    renderApp('/camere/cam-terasa/zone');
    await screen.findByText(/Ultima captură a camerei/, undefined, { timeout: 5000 });
    const file = new File(['x'], 'terasa.png', { type: 'image/png' });
    await user.upload(screen.getByLabelText('Încarcă o imagine din cameră'), file);
    expect(await screen.findByText(/Captură încărcată/)).toHaveTextContent(
      'Captură încărcată · Schimbă',
    );
    expect(screen.queryByRole('button', { name: 'Folosește imaginea live' })).toBeNull();
  });

  it('switches camera from the editor, each with its own zones and still', async () => {
    const user = userEvent.setup();
    const api = renderApp();
    const capture = vi.spyOn(api, 'captureFrame');
    const save = vi.spyOn(api, 'saveZones');
    const pick = await screen.findByRole('group', { name: 'Camera' }, { timeout: 5000 });
    expect(within(pick).getByRole('button', { name: 'Sala principală' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await user.click(within(pick).getByRole('button', { name: 'Terasă · offline' }));
    expect(await screen.findByRole('heading', { name: /Zone · Terasă/ })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: '1 zonă' })).toBeInTheDocument();
    expect(await screen.findByAltText(/Ultima captură de la Terasă/)).toBeInTheDocument();
    expect(capture).toHaveBeenCalledWith('cam-terasa');

    // Unsaved changes ask first, then save to this camera only.
    await user.click(screen.getByRole('button', { name: /Masa 3/ }));
    await user.click(screen.getByRole('button', { name: /Șterge/ }));
    await user.click(
      within(screen.getByRole('group', { name: 'Camera' })).getByRole('button', {
        name: 'Sala principală',
      }),
    );
    const dialog = await screen.findByRole('dialog', { name: /nesalvate pe Terasă/ });
    await user.click(within(dialog).getByRole('button', { name: 'Salvează și pleacă' }));
    expect(save).toHaveBeenCalledWith('cam-terasa', []);
    expect(await screen.findByRole('heading', { name: /Zone · Sala principală/ })).toBeVisible();
    expect(await screen.findByRole('heading', { name: '3 zone' })).toBeInTheDocument();
  });

  it('falls back to the schematic room until the camera has sent a still', async () => {
    const api = renderApp();
    vi.spyOn(api, 'captureFrame').mockRejectedValue(new Error('404'));
    expect(
      await screen.findByText(/Imagine de probă/, undefined, { timeout: 5000 }),
    ).toHaveTextContent('Imagine de probă · Încarcă o captură');
  });

  it('says saved with a way out, and asks to save only after a change', async () => {
    const user = userEvent.setup();
    renderApp();
    expect(await screen.findByText('salvat', undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Gata' })).toHaveAttribute('href', '/dispozitive');
    expect(screen.queryByRole('button', { name: 'Salvează zonele' })).toBeNull();

    await user.click(screen.getByRole('button', { name: /Masa 2/ }));
    await user.click(screen.getByRole('button', { name: /Șterge/ }));
    expect(screen.getByText('modificări nesalvate')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Salvează zonele' }));
    expect(await screen.findByText('2 zone salvate')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Gata' })).toBeInTheDocument();
  });
});
