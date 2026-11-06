import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { ApiContext } from '../api/context';
import { MockApi } from '../api/mock';
import { MOCK_PASSWORD } from '../api/mockAccounts';
import { AuthProvider } from '../auth/AuthProvider';
import * as burst from '../staff/burst';
import { Toaster } from '../ui/Toaster';

function renderPage(email = 'manager@aivee.demo') {
  const api = new MockApi({ latencyMs: 0, autoplay: false });
  api.accounts.login(email, MOCK_PASSWORD);
  render(
    <ApiContext.Provider value={api}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/angajat-nou']}>
          <Toaster>
            <App />
          </Toaster>
        </MemoryRouter>
      </AuthProvider>
    </ApiContext.Provider>,
  );
  return api;
}

/** A phone camera for jsdom: a stream whose track we can watch being stopped. */
function fakeCamera() {
  const stop = vi.fn();
  const stream = { getTracks: () => [{ stop }] } as unknown as MediaStream;
  const getUserMedia = vi.fn(async () => stream);
  vi.stubGlobal('isSecureContext', true);
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia },
  });
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
  return { getUserMedia, stop };
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('NewStaffPage (/angajat-nou)', () => {
  it('films on this phone, uploads the shots, and saves only the kept crops', async () => {
    const user = userEvent.setup();
    const { getUserMedia, stop } = fakeCamera();
    const shots = [new Blob(['a']), new Blob(['b']), new Blob(['c'])];
    const burstSpy = vi.spyOn(burst, 'captureBurst').mockResolvedValue(shots);
    const api = renderPage();
    const upload = vi.spyOn(api, 'uploadStaffFrames');
    const confirm = vi.spyOn(api, 'confirmStaffCapture');

    await screen.findByRole('heading', { name: 'Adaugă angajat' }, { timeout: 5000 });
    await user.type(screen.getByLabelText('Nume'), 'Maria');
    await user.click(screen.getByRole('button', { name: 'Pornește camera' }));
    expect(getUserMedia).toHaveBeenCalledWith({
      video: { facingMode: 'environment', width: { ideal: 1280 } },
      audio: false,
    });
    expect(screen.getByText(/ține telefonul la 2–3 m/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Start \(20 s\)/ }));
    expect(burstSpy).toHaveBeenCalledWith(expect.objectContaining({ seconds: 20 }));
    expect(upload).toHaveBeenCalledWith(shots);

    const thumbs = await screen.findAllByRole('button', { name: /Imaginea \d/ });
    expect(thumbs).toHaveLength(3);
    expect(stop).toHaveBeenCalled(); // the camera is released once the shots are up
    await user.click(thumbs[0] as HTMLElement);
    await user.click(screen.getByRole('button', { name: 'Salvează' }));

    expect(confirm).toHaveBeenCalledWith(expect.any(String), { keep: [1, 2], name: 'Maria' });
    const done = await screen.findByText(/ești recunoscut ca angajat la toate camerele/);
    expect(within(done).getByText('Maria')).toBeInTheDocument();
  });

  it('needs a name, and explains HTTPS when the browser has no camera', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole('button', { name: 'Pornește camera' }, { timeout: 5000 }),
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Scrie numele angajatului.');
    await user.type(screen.getByLabelText('Nume'), 'Ion');
    await user.click(screen.getByRole('button', { name: 'Pornește camera' }));
    expect(screen.getByRole('alert')).toHaveTextContent(/adresă sigură \(HTTPS\)/);
  });

  it('shows a refused camera in Romanian and stays on step 1', async () => {
    const user = userEvent.setup();
    const { getUserMedia } = fakeCamera();
    getUserMedia.mockRejectedValueOnce(new DOMException('no', 'NotAllowedError'));
    renderPage();
    await user.type(await screen.findByLabelText('Nume', {}, { timeout: 5000 }), 'Ion');
    await user.click(screen.getByRole('button', { name: 'Pornește camera' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Ai refuzat accesul la cameră');
    expect(screen.getByLabelText('Nume')).toBeInTheDocument();
  });
});
