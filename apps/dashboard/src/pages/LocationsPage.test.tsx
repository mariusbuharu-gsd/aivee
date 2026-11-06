import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { fakeApi, renderWithApi } from '../test/fakeApi';
import { LocationsPage } from './LocationsPage';

const DEMO = { id: 'demo', name: 'Terasa demo', type: 'restaurant', telegram_chat_id: null };

describe('LocationsPage Telegram', () => {
  it('offers "Conectează Telegram" in the edit form, the chat id under Avansat', async () => {
    const updateLocation = vi.fn(async () => DEMO);
    const api = fakeApi({ listLocations: vi.fn(async () => [DEMO]), updateLocation });
    renderWithApi(<LocationsPage />, api);
    await userEvent.click(
      await screen.findByRole('button', { name: 'Acțiuni pentru Terasa demo' }),
    );
    await userEvent.click(screen.getByRole('menuitem', { name: 'Modifică' }));

    const group = screen.getByRole('group', { name: 'Alerte pe Telegram' });
    expect(within(group).getByRole('button', { name: 'Conectează Telegram' })).toBeVisible();
    expect(within(group).getByText('Avansat: id-ul chatului')).toBeInTheDocument();
    expect(within(group).getByLabelText(/Chat Telegram/)).not.toBeVisible();

    // Saving without touching the chat id never overwrites a chat the bot linked meanwhile.
    await userEvent.click(screen.getByRole('button', { name: 'Salvează' }));
    expect(updateLocation).toHaveBeenCalledWith('demo', {
      name: 'Terasa demo',
      type: 'restaurant',
    });
  });
});
