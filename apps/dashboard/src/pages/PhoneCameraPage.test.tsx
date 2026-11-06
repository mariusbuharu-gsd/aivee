import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { ApiContext } from '../api/context';
import { MockApi } from '../api/mock';
import { MOCK_PASSWORD } from '../api/mockAccounts';
import { AuthProvider } from '../auth/AuthProvider';
import { Toaster } from '../ui/Toaster';
import { cameraProblem } from '../phone/problems';

async function renderPhone(path: string) {
  const api = new MockApi({ latencyMs: 0, autoplay: false });
  await api.createCamera({
    id: 'tel-01',
    name: 'Telefon sală',
    source: 'mqtt-frames://tel-01',
    device: 'edge-sala',
  });
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

describe('PhoneCameraPage', () => {
  it('preselects the cloud camera from the QR link and starts stopped', async () => {
    await renderPhone('/telefon?camera=tel-01');
    expect(
      await screen.findByRole('heading', { name: 'Telefonul ca cameră' }, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(await screen.findByRole('combobox', { name: 'Camera' })).toHaveTextContent(
      'Telefon sală',
    );
    expect(screen.getByRole('status', { name: '' })).toHaveTextContent('Oprit');
  });

  it('warns when the linked camera is not a cloud camera', async () => {
    await renderPhone('/telefon?camera=cam-sala');
    expect(
      await screen.findByText(
        'Camera aceasta nu primește imagini de la telefon',
        {},
        { timeout: 5000 },
      ),
    ).toBeInTheDocument();
  });

  it('explains that the camera needs HTTPS (jsdom has no camera)', async () => {
    const user = userEvent.setup();
    await renderPhone('/telefon?camera=tel-01');
    await user.click(
      await screen.findByRole('button', { name: /Pornește camera/ }, { timeout: 5000 }),
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/adresă sigură \(HTTPS\)/);
  });
});

describe('cameraProblem', () => {
  it('turns a refused permission into a Romanian next step', () => {
    const p = cameraProblem(new DOMException('denied', 'NotAllowedError'));
    expect(p.title).toBe('Ai refuzat accesul la cameră');
    expect(p.text).toMatch(/Permite camera/);
    expect(cameraProblem(new DOMException('busy', 'NotReadableError')).title).toMatch(
      /altă aplicație/,
    );
  });
});
