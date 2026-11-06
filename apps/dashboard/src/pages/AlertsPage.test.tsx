import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { ApiContext } from '../api/context';
import { MockApi } from '../api/mock';
import { MOCK_PASSWORD } from '../api/mockAccounts';
import { AuthProvider } from '../auth/AuthProvider';
import { Toaster } from '../ui/Toaster';

function renderAlerts(email = 'manager@aivee.demo') {
  const api = new MockApi({ latencyMs: 0, autoplay: false });
  api.accounts.login(email, MOCK_PASSWORD);
  render(
    <ApiContext.Provider value={api}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/alerte']}>
          <Toaster>
            <App />
          </Toaster>
        </MemoryRouter>
      </AuthProvider>
    </ApiContext.Provider>,
  );
  return api;
}

/** Closed rows on the page, across the day groups. */
const closedRows = () =>
  document.querySelectorAll('.alerts-main ul[aria-label="Alerte închise"] > li').length;

beforeEach(() => localStorage.clear());

describe('Alerte', () => {
  it('shows the first 20 closed alerts, then "Mai multe" loads the next page', async () => {
    const user = userEvent.setup();
    const api = renderAlerts();
    const listAlerts = vi.spyOn(api, 'listAlerts');
    const more = await screen.findByRole('button', { name: 'Mai multe' });
    await waitFor(() => expect(closedRows()).toBe(20));

    await user.click(more);
    await waitFor(() => expect(closedRows()).toBe(33));
    // The first API page (50 events) did not hold them all: the next one was asked for.
    expect(listAlerts).toHaveBeenCalledWith(
      expect.objectContaining({ before: expect.any(String) }),
    );
    expect(screen.queryByRole('button', { name: 'Mai multe' })).toBeNull();
  });

  it('pages the Închise filter the same way', async () => {
    const user = userEvent.setup();
    renderAlerts();
    await user.click(await screen.findByRole('button', { name: 'Închise' }));
    await waitFor(() => expect(closedRows()).toBe(20));
    expect(screen.getByRole('button', { name: 'Mai multe' })).toBeInTheDocument();
  });

  it('the Personal card keeps the questions up front and folds the uniform photos', async () => {
    renderAlerts('owner@aivee.demo');
    const side = await screen.findByRole('complementary', { name: 'Personal și notificări' });
    const staff = within(side).getByRole('region', { name: 'Personal' });
    expect(within(staff).getByRole('link', { name: 'Adaugă angajat → Camere' })).toHaveAttribute(
      'href',
      '/dispozitive',
    );
    const photo = within(staff).getByText('Încarcă poză uniformă');
    expect(photo.closest('details')).not.toHaveAttribute('open');
    expect(within(side).getByRole('region', { name: 'Alerte pe Telegram' })).toBeInTheDocument();
  });

  it('shows no Telegram card to a manager', async () => {
    renderAlerts();
    const side = await screen.findByRole('complementary', { name: 'Personal și notificări' });
    await within(side).findByRole('region', { name: 'Personal' });
    expect(within(side).queryByRole('region', { name: 'Alerte pe Telegram' })).toBeNull();
  });
});
