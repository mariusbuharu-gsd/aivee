import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { ApiError, type StaffCapture } from '../api/client';
import { ApiContext } from '../api/context';
import { MockApi } from '../api/mock';
import { MOCK_PASSWORD } from '../api/mockAccounts';
import { AuthProvider } from '../auth/AuthProvider';
import { Toaster } from '../ui/Toaster';

function renderApp(
  email = 'manager@aivee.demo',
  api = new MockApi({ latencyMs: 0, autoplay: false }),
) {
  api.accounts.login(email, MOCK_PASSWORD);
  render(
    <ApiContext.Provider value={api}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/dispozitive']}>
          <Toaster>
            <App />
          </Toaster>
        </MemoryRouter>
      </AuthProvider>
    </ApiContext.Provider>,
  );
  return api;
}

const CAPTURE: StaffCapture = {
  token: 'tok-1',
  camera_id: 'cam-01',
  frames: 12,
  candidates: [0, 1, 2].map((index) => ({ index, thumbnail: `data:image/jpeg;base64,${index}` })),
  expires_in_s: 600,
};

async function openOnFirstCamera() {
  const user = userEvent.setup();
  const cards = await screen.findAllByRole('listitem', { name: /^Camera / }, { timeout: 5000 });
  await user.click(within(cards[0] as HTMLElement).getByRole('button', { name: /Adaugă angajat/ }));
  return { user, dialog: await screen.findByRole('dialog', { name: 'Adaugă angajat' }) };
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe('Adaugă angajat (guided capture)', () => {
  it('goes name → camera → candidates → saved, sending only the kept crops', async () => {
    const api = new MockApi({ latencyMs: 0, autoplay: false });
    const capture = vi.spyOn(api, 'captureStaff').mockResolvedValue(CAPTURE);
    const confirm = vi.spyOn(api, 'confirmStaffCapture').mockResolvedValue({
      profile: { id: 'staff-1', name: 'Ana', description_ro: '', examples: 2, has_centroid: true },
      examples_added: 2,
      published: true,
    });
    renderApp('manager@aivee.demo', api);
    const { user, dialog } = await openOnFirstCamera();

    expect(within(dialog).getByText('Fă-o de pe telefon')).toBeInTheDocument();
    expect(
      within(dialog).getByRole('img', { name: /Cod QR pentru Adaugă angajat/ }),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Mai departe' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Scrie numele angajatului.');
    await user.type(within(dialog).getByLabelText('Nume'), 'Ana');
    await user.click(within(dialog).getByRole('button', { name: 'Mai departe' }));

    expect(within(dialog).getByText(/rotește-te încet/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: /Start/ }));
    expect(capture).toHaveBeenCalledWith(expect.any(String), 20);

    const thumbs = await within(dialog).findAllByRole('button', { name: /Imaginea \d/ });
    expect(thumbs).toHaveLength(3);
    thumbs.forEach((t) => expect(t).toHaveAttribute('aria-pressed', 'true'));
    await user.click(thumbs[1] as HTMLElement);
    expect(thumbs[1]).toHaveAttribute('aria-pressed', 'false');
    expect(within(dialog).getByText(/Păstrezi 2 din 3/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Salvează' }));
    expect(confirm).toHaveBeenCalledWith('tok-1', { keep: [0, 2], name: 'Ana' });
    const done = await screen.findByRole('dialog', { name: 'Gata!' });
    expect(within(done).getByRole('status')).toHaveTextContent('Profil publicat la camere: Ana');
  });

  it('can add to an existing profile instead of creating one', async () => {
    const api = new MockApi({ latencyMs: 0, autoplay: false });
    vi.spyOn(api, 'listStaffProfiles').mockResolvedValue([
      { id: 'uniforma', name: 'Uniformă', description_ro: '', examples: 3, has_centroid: true },
    ]);
    vi.spyOn(api, 'captureStaff').mockResolvedValue(CAPTURE);
    const confirm = vi.spyOn(api, 'confirmStaffCapture');
    renderApp('manager@aivee.demo', api);
    const { user, dialog } = await openOnFirstCamera();

    await user.click(await within(dialog).findByRole('combobox', { name: 'Profil' }));
    await user.click(await screen.findByRole('option', { name: /Uniformă/ }));
    expect(within(dialog).queryByLabelText('Nume')).toBeNull();
    await user.click(within(dialog).getByRole('button', { name: 'Mai departe' }));
    await user.click(within(dialog).getByRole('button', { name: /Start/ }));
    await within(dialog).findAllByRole('button', { name: /Imaginea \d/ });
    await user.click(within(dialog).getByRole('button', { name: 'Salvează' }));
    expect(confirm).toHaveBeenCalledWith('tok-1', { keep: [0, 1, 2], profile_id: 'uniforma' });
  });

  it('shows the API error in Romanian and lets you retry', async () => {
    const api = new MockApi({ latencyMs: 0, autoplay: false });
    vi.spyOn(api, 'captureStaff').mockRejectedValueOnce(
      new ApiError('Camera nu trimite imagini acum.', 'not_found', 404),
    );
    renderApp('manager@aivee.demo', api);
    const { user, dialog } = await openOnFirstCamera();
    await user.type(within(dialog).getByLabelText('Nume'), 'Ion');
    await user.click(within(dialog).getByRole('button', { name: 'Mai departe' }));
    await user.click(within(dialog).getByRole('button', { name: /Start/ }));
    expect(await within(dialog).findByText('Camera nu trimite imagini acum.')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /Start/ })).toBeEnabled();
  });

  it('is hidden without staff.enrol', async () => {
    renderApp('staff@aivee.demo');
    // staff cannot open Dispozitive at all; the button never shows for them
    expect(screen.queryByRole('button', { name: /Adaugă angajat/ })).toBeNull();
  });
});
