import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it } from 'vitest';
import { App } from '../App';
import { ApiContext } from '../api/context';
import { MockApi } from '../api/mock';
import { MOCK_PASSWORD } from '../api/mockAccounts';
import { AuthProvider } from '../auth/AuthProvider';
import { Toaster } from '../ui/Toaster';

function renderLive(email: string, open = true) {
  const api = new MockApi({ latencyMs: 0, autoplay: false });
  if (open) {
    api.emitAlert('r-neservit', 'z-masa-2', 'opened', 'Masa 2: nimeni de la personal de 1 minut');
  }
  api.accounts.login(email, MOCK_PASSWORD);
  render(
    <ApiContext.Provider value={api}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/']}>
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

describe('Live', () => {
  it('says the room is fine when nobody waits', async () => {
    renderLive('manager@aivee.demo', false);
    expect(await screen.findByText('Totul e în regulă.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Alerte deschise' })).toBeNull();
    expect(screen.getByText('Sala e liniștită')).toBeInTheDocument();
  });

  it('leads with the open alert: band, hot zone on the camera and "Sala acum"', async () => {
    renderLive('manager@aivee.demo');
    expect(await screen.findByText('O masă așteaptă.')).toBeInTheDocument();
    const band = screen.getByRole('list', { name: 'Alerte deschise' });
    expect(within(band).getByText('Masa 2: nimeni de la personal de 1 minut')).toBeInTheDocument();
    expect(within(band).getByText('Nimeni nu a preluat încă')).toBeInTheDocument();
    expect(within(band).getByRole('timer')).toBeInTheDocument();
    const room = await screen.findByRole('article', { name: 'Camera Sala principală' });
    expect(within(room).getByText(/^Masa 2 · \d+:\d{2}$/)).toBeInTheDocument();
    expect(screen.getByText('Masa 2 așteaptă')).toBeInTheDocument();
    // The offline camera is one row, after the cameras that see.
    const terrace = screen.getByRole('article', { name: 'Camera Terasă' });
    expect(within(terrace).getByText('Dispozitiv offline')).toBeInTheDocument();
  });

  it('the Alerte nav count is the number of open alerts, like the Deschise filter', async () => {
    const api = renderLive('manager@aivee.demo');
    api.emitSuggestion();
    const nav = await screen.findByRole('link', { name: /Alerte/ });
    await waitFor(() => expect(within(nav).getByLabelText('1 deschise')).toHaveTextContent('1'));
    expect(screen.getAllByLabelText(/^\d+ (deschise|noi)$/)).toHaveLength(1);
  });

  it('"Merg eu" on the band tells colleagues who goes, the alert stays open', async () => {
    const user = userEvent.setup();
    renderLive('staff@aivee.demo');
    await user.click(await screen.findByRole('button', { name: 'Merg eu la Masa 2' }));
    const band = screen.getByRole('list', { name: 'Alerte deschise' });
    await waitFor(() =>
      expect(within(band).getByText('Ana Dumitru merge la Masa 2')).toBeInTheDocument(),
    );
    expect(within(band).queryByRole('button', { name: /Merg eu/ })).toBeNull();
    expect(screen.getByText('Ai preluat Masa 2')).toBeInTheDocument();
  });
});
