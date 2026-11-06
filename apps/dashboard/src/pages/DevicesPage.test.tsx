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

function renderApp(
  path = '/dispozitive',
  email = 'manager@aivee.demo',
  api = new MockApi({ latencyMs: 0, autoplay: false }),
) {
  api.accounts.login(email, MOCK_PASSWORD);
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

describe('DevicesPage', () => {
  it('keeps the latency unit out of the monospace span, which made "0.9 s" read as "0.9  s"', async () => {
    renderApp();
    const line = await screen.findByText(/Latență alertă/, {}, { timeout: 5000 });
    expect(line.textContent).toMatch(/Latență alertă \d+\.\d s · /);
    const num = within(line).getByText(/^\d+\.\d$/);
    expect(num).toHaveClass('mono');
  });

  it('puts health on the card and drops the separate system table', async () => {
    renderApp();
    const sala = await screen.findByRole(
      'listitem',
      { name: 'Camera Sala principală' },
      { timeout: 5000 },
    );
    expect(within(sala).getByText('FPS')).toBeInTheDocument();
    expect(within(sala).getByText('CPU')).toBeInTheDocument();
    expect(within(sala).getByText('rtsp://192.168.1.20/…')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Sistem' })).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('shows the full source only while editing, masked everywhere else', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(
      await screen.findByRole(
        'button',
        { name: 'Acțiuni pentru camera Sala principală' },
        { timeout: 5000 },
      ),
    );
    await user.click(screen.getByRole('menuitem', { name: 'Editează camera' }));
    const dialog = screen.getByRole('dialog', { name: /Editezi „Sala principală”/ });
    const source = within(dialog).getByLabelText('Adresa sursei');
    expect(source).toHaveValue('rtsp://192.168.1.20:554/stream1');
    await user.clear(source);
    await user.type(source, 'rtsp://admin:hunter2@192.168.1.20:554/stream1');
    await user.click(within(dialog).getByRole('button', { name: 'Salvează' }));

    const sala = await screen.findByRole(
      'listitem',
      { name: 'Camera Sala principală' },
      { timeout: 5000 },
    );
    expect(await within(sala).findByText('rtsp://••••@192.168.1.20/…')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('hunter2');
  });

  it('lists what to check on an offline device and asks again on retry', async () => {
    const user = userEvent.setup();
    const api = renderApp();
    const terrace = await screen.findByRole(
      'listitem',
      { name: 'Camera Terasă' },
      { timeout: 5000 },
    );
    const steps = within(terrace).getByRole('list');
    expect(within(steps).getAllByRole('listitem')).toHaveLength(3);
    expect(within(terrace).queryByText('FPS')).toBeNull();

    const list = vi.spyOn(api, 'listCameras');
    await user.click(
      within(terrace).getByRole('button', { name: 'Am verificat, încearcă din nou' }),
    );
    expect(list).toHaveBeenCalled();
    expect(await screen.findByText(/tot nu răspunde/)).toBeInTheDocument();
  });

  it('says when an online camera last sent a frame and how long an offline one is gone', async () => {
    renderApp();
    const sala = await screen.findByRole(
      'listitem',
      { name: 'Camera Sala principală' },
      { timeout: 5000 },
    );
    expect(await within(sala).findByText(/^ultima imagine acum \d+ s$/)).toBeInTheDocument();
    const terrace = screen.getByRole('listitem', { name: 'Camera Terasă' });
    expect(await within(terrace).findByText('offline de 14 min')).toBeInTheDocument();
  });

  it('shows a recent blurred still on each camera card', async () => {
    renderApp();
    const sala = await screen.findByRole(
      'listitem',
      { name: 'Camera Sala principală' },
      { timeout: 5000 },
    );
    const img = await within(sala).findByRole('img', { name: /Captură de la Sala principală/ });
    expect(img.getAttribute('src')).toMatch(/^data:image\/svg\+xml,/);
    expect(within(sala).getByText(/^captură de acum \d+ s$/)).toBeInTheDocument();
  });

  it('keeps a quiet placeholder when there is no still', async () => {
    const api = new MockApi({ latencyMs: 0, autoplay: false });
    vi.spyOn(api, 'captureFrame').mockRejectedValue(new Error('404'));
    renderApp(undefined, undefined, api);
    const sala = await screen.findByRole(
      'listitem',
      { name: 'Camera Sala principală' },
      { timeout: 5000 },
    );
    expect(await within(sala).findByText('Nicio captură încă')).toBeInTheDocument();
    expect(within(sala).queryByRole('img', { name: /Captură de la/ })).toBeNull();
  });

  it('offers a QR to use a phone as a cloud camera, and only for cloud cameras', async () => {
    const user = userEvent.setup();
    const api = new MockApi({ latencyMs: 0, autoplay: false });
    await api.createCamera({
      id: 'tel-01',
      name: 'Telefon',
      source: 'mqtt-frames://tel-01',
      device: 'edge-sala',
    });
    renderApp('/dispozitive', 'manager@aivee.demo', api);
    await user.click(
      await screen.findByRole(
        'button',
        { name: 'Acțiuni pentru camera Sala principală' },
        { timeout: 5000 },
      ),
    );
    expect(screen.queryByRole('menuitem', { name: 'Folosește telefonul' })).toBeNull();
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', { name: 'Acțiuni pentru camera Telefon' }));
    await user.click(screen.getByRole('menuitem', { name: 'Folosește telefonul' }));
    const dialog = screen.getByRole('dialog', { name: /Folosește telefonul/ });
    const url = `${window.location.origin}/telefon?camera=tel-01`;
    expect(within(dialog).getByRole('img', { name: /Cod QR/ })).toBeInTheDocument();
    expect(within(dialog).getByText(url)).toBeInTheDocument();
  });
});
