import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { ApiError } from '../api/client';
import { ApiContext } from '../api/context';
import { MockApi } from '../api/mock';
import { MOCK_PASSWORD } from '../api/mockAccounts';
import { AuthProvider } from '../auth/AuthProvider';
import { Toaster } from '../ui/Toaster';
import { clock } from '../alerts/format';

function renderApp(path = '/video', email = 'manager@aivee.demo') {
  const api = new MockApi({ latencyMs: 0, autoplay: false });
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

const clip = (name = 'terasa.mp4', type = 'video/mp4') => new File(['x'], name, { type });

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe('clock', () => {
  it('formats a clip position as mm:ss', () => {
    expect(clock(0)).toBe('00:00');
    expect(clock(12.4)).toBe('00:12');
    expect(clock(95)).toBe('01:35');
  });
});

describe('VideoPage', () => {
  it('shows the demo clip and the timeline of its alerts', async () => {
    renderApp();
    expect(await screen.findByRole('heading', { name: 'Analiză video' })).toBeVisible();
    expect(screen.getByText(/Nu trimite notificări personalului/)).toBeInTheDocument();
    const list = await screen.findByRole('list', { name: 'Clipuri încărcate' });
    const demo = within(list).getByRole('button', { name: /sala-1\.mp4/ });
    expect(demo).toHaveAttribute('aria-pressed', 'true');
    expect(within(demo).getByText('Gata')).toBeInTheDocument();
    expect(within(demo).getByText(/01:35 · 4 alerte/)).toBeInTheDocument();

    const timeline = await screen.findByRole('list', { name: 'Alerte din clip' });
    const rows = await within(timeline).findAllByRole('listitem');
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent('00:12');
    expect(rows[0]).toHaveTextContent('Masa 2: neservită de 1 min');
    expect(rows[0]).toHaveTextContent('ajuns 00:41');
    expect(rows[0]).toHaveTextContent('închisă 00:43');
    expect(within(rows[0] as HTMLElement).getByText('Ajuns')).toBeInTheDocument();
    expect(rows[3]).toHaveTextContent('01:20');
    expect(rows[3]).toHaveTextContent('sfârșitul clipului');
  });

  it('uploads the clip with the source camera and the rotation', async () => {
    const user = userEvent.setup();
    const upload = vi.spyOn(MockApi.prototype, 'uploadVideo');
    renderApp();
    await screen.findByRole('list', { name: 'Clipuri încărcate' });
    const file = clip();
    await user.upload(screen.getByLabelText('Alege clipul'), file);
    expect(screen.getByText('terasa.mp4')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /Copiază zonele/ })).toHaveTextContent(
        'Sala principală',
      ),
    );
    await user.click(screen.getByRole('combobox', { name: 'Rotire' }));
    await user.click(screen.getByRole('option', { name: /90°/ }));
    await user.click(screen.getByRole('button', { name: 'Analizează' }));

    expect(upload).toHaveBeenCalledWith({
      file,
      rotate: 90,
      copy_from_camera_id: 'cam-sala',
    });
    const list = screen.getByRole('list', { name: 'Clipuri încărcate' });
    const item = await within(list).findByRole('button', { name: /terasa\.mp4/ });
    expect(item).toHaveAttribute('aria-pressed', 'true');
    expect(within(item).getByText('În așteptare')).toBeInTheDocument();
  });

  it('refuses a clip over 200 MB before calling the API', async () => {
    const user = userEvent.setup();
    const upload = vi.spyOn(MockApi.prototype, 'uploadVideo');
    renderApp();
    await screen.findByRole('list', { name: 'Clipuri încărcate' });
    const big = clip('mare.mp4');
    Object.defineProperty(big, 'size', { value: 201 * 1024 * 1024 });
    await user.upload(screen.getByLabelText('Alege clipul'), big);
    await user.click(screen.getByRole('button', { name: 'Analizează' }));
    expect(screen.getByText(/mai mare de 200 MB/)).toBeInTheDocument();
    expect(upload).not.toHaveBeenCalled();
  });

  it("shows the API's Romanian message when the upload is refused", async () => {
    const user = userEvent.setup();
    vi.spyOn(MockApi.prototype, 'uploadVideo').mockRejectedValue(
      new ApiError('Clipul are mai mult de 2 minute.', 'too_long', 422),
    );
    renderApp();
    await screen.findByRole('list', { name: 'Clipuri încărcate' });
    await user.upload(screen.getByLabelText('Alege clipul'), clip('lung.mp4'));
    await user.click(screen.getByRole('button', { name: 'Analizează' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Clipul are mai mult de 2 minute.');
  });

  it('is hidden from staff', async () => {
    const list = vi.spyOn(MockApi.prototype, 'listVideos');
    renderApp('/video', 'staff@aivee.demo');
    const nav = await screen.findByRole('navigation', { name: 'Principal' });
    expect(within(nav).queryByRole('link', { name: /Analiză video/ })).toBeNull();
    expect(await screen.findByRole('heading', { name: 'Live' })).toBeVisible();
    expect(list).not.toHaveBeenCalled();
  });

  it('lists the page in the sidebar for a manager', async () => {
    renderApp('/');
    const nav = await screen.findByRole('navigation', { name: 'Principal' });
    expect(within(nav).getByRole('link', { name: /Analiză video/ })).toHaveAttribute(
      'href',
      '/video',
    );
  });
});
