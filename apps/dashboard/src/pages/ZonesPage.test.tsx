import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it } from 'vitest';
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
}

beforeEach(() => localStorage.clear());

describe('ZonesPage', () => {
  it('draws from the toolbar on the image, one tool per zone kind', async () => {
    const user = userEvent.setup();
    renderApp();
    const tools = await screen.findByRole(
      'toolbar',
      { name: 'Unelte de desen' },
      { timeout: 5000 },
    );
    for (const label of ['Masă', 'Intrare', 'Personal']) {
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
