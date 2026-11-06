import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import type { ApiClient, Me, Member, PendingInvite } from '../api/client';
import { ApiContext } from '../api/context';
import { ROLE_PERMISSIONS } from '../api/mockAccounts';
import { AuthContext } from '../auth/context';
import { FAKE_ME, fakeApi, fakeAuth, renderWithApi } from '../test/fakeApi';
import { Toaster } from '../ui/Toaster';
import { TeamPage } from './TeamPage';

const OWNER: Me = {
  ...FAKE_ME,
  is_owner: true,
  locations: FAKE_ME.locations.map((l) => ({
    ...l,
    role: 'owner',
    permissions: ROLE_PERMISSIONS.owner,
  })),
};

const MIHAI: Member = {
  user_id: 'u-2',
  name: 'Mihai Ionescu',
  email: 'mihai@aivee.demo',
  role: 'staff',
};
const PENDING: PendingInvite = {
  id: 'inv-old',
  email: 'nou@aivee.demo',
  role: 'staff',
  location_id: 'demo',
  created_by: 'u-1',
  created_at: '2026-11-06T10:00:00Z',
  expires_at: '2026-11-13T10:00:00Z',
};

function renderAsOwner(api: ApiClient) {
  render(
    <ApiContext.Provider value={api}>
      <AuthContext.Provider value={fakeAuth(OWNER)}>
        <MemoryRouter>
          <Toaster>
            <TeamPage />
          </Toaster>
        </MemoryRouter>
      </AuthContext.Provider>
    </ApiContext.Provider>,
  );
}

describe('TeamPage', () => {
  it('shows the role as text and changes it from the ⋯ menu', async () => {
    const updateMember = vi.fn(async () => ({ ...MIHAI, role: 'manager' as const }));
    renderAsOwner(fakeApi({ listMembers: vi.fn(async () => [MIHAI]), updateMember }));

    const row = (await screen.findByText('Mihai Ionescu')).closest('li') as HTMLElement;
    expect(within(row).queryByRole('combobox')).toBeNull();
    expect(within(row).getByText('Personal')).toBeVisible();
    await userEvent.click(
      within(row).getByRole('button', { name: 'Acțiuni pentru Mihai Ionescu' }),
    );
    await userEvent.click(screen.getByRole('menuitem', { name: 'Schimbă rolul în manager' }));
    expect(updateMember).toHaveBeenCalledWith('demo', 'u-2', 'manager');
  });

  it('draws a QR code for a new invite link', async () => {
    const createInvite = vi.fn(async () => ({
      invite_url: 'http://localhost:5173/invitatie/abc',
      expires_at: '2026-11-13T10:00:00Z',
    }));
    renderWithApi(<TeamPage />, fakeApi({ createInvite }));
    await userEvent.type(screen.getByLabelText('Email'), 'ana@restaurant.ro');
    await userEvent.click(screen.getByRole('button', { name: /Creează linkul/ }));
    expect(await screen.findByRole('img', { name: /Cod QR/ })).toBeInTheDocument();
    expect(screen.getByLabelText('Link de invitație')).toHaveValue(
      'http://localhost:5173/invitatie/abc',
    );
  });

  it('re-issues an older pending invite to copy its link', async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
    const createInvite = vi.fn(async () => ({
      invite_url: 'http://localhost:5173/invitatie/fresh',
      expires_at: '2026-11-13T10:00:00Z',
    }));
    const revokeInvite = vi.fn(async () => undefined);
    renderWithApi(
      <TeamPage />,
      fakeApi({ listInvites: vi.fn(async () => [PENDING]), createInvite, revokeInvite }),
    );
    await user.click(await screen.findByRole('button', { name: 'Copiază link' }));
    expect(createInvite).toHaveBeenCalledWith({
      location_id: 'demo',
      role: 'staff',
      email: 'nou@aivee.demo',
    });
    expect(revokeInvite).toHaveBeenCalledWith('inv-old');
    expect(writeText).toHaveBeenCalledWith('http://localhost:5173/invitatie/fresh');
    expect(await screen.findByText('Link copiat')).toBeInTheDocument();
  });
});
