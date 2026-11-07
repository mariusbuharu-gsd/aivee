import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import type { ApiClient, CameraView, Me, Role } from '../api/client';
import { ApiContext } from '../api/context';
import { ROLE_PERMISSIONS } from '../api/mockAccounts';
import { AuthContext } from '../auth/context';
import type { Rule } from '../contracts';
import type { PushService, PushState } from '../push/service';
import { isTestSent } from '../setup/checklist';
import { LiveDataContext, type LiveData } from '../state/context';
import { FAKE_ME, fakeApi, fakeAuth } from '../test/fakeApi';
import { Toaster } from '../ui/Toaster';
import { SetupChecklist } from './SetupChecklist';

const camera: CameraView = {
  id: 'cam-sala',
  name: 'Sala',
  source: 'rtsp://x',
  device: 'edge',
  online: true,
  zones: [{ id: 'z', name: 'Masa 1', tag: 'table', polygon: [] } as never],
};
const rule = { id: 'r', camera_id: 'cam-sala', enabled: true } as Rule;

function fakePush(state: PushState, sent = 1) {
  return {
    supported: true,
    state: vi.fn(async () => state),
    sendTest: vi.fn(async () => ({ sent, removed: 0, failed: 0 })),
  } as unknown as PushService;
}

function meAs(role: Role): Me {
  const [loc] = FAKE_ME.locations;
  if (!loc) throw new Error('FAKE_ME has a location');
  return {
    ...FAKE_ME,
    is_owner: role === 'owner',
    locations: [{ ...loc, role, permissions: [...ROLE_PERMISSIONS[role]] }],
  };
}

function setup({
  role = 'manager',
  cameras = [camera],
  rules = [rule],
  push = fakePush('unavailable'),
  api = fakeApi(),
}: {
  role?: Role;
  cameras?: CameraView[];
  rules?: Rule[];
  push?: PushService;
  api?: ApiClient;
} = {}) {
  const live = { cameras, rules, loading: false } as unknown as LiveData;
  render(
    <ApiContext.Provider value={api}>
      <AuthContext.Provider value={fakeAuth(meAs(role))}>
        <LiveDataContext.Provider value={live}>
          <MemoryRouter>
            <Toaster>
              <SetupChecklist push={push} />
            </Toaster>
          </MemoryRouter>
        </LiveDataContext.Provider>
      </AuthContext.Provider>
    </ApiContext.Provider>,
  );
  return { api, push };
}

const step = (id: string) => document.querySelector(`[data-step="${id}"]`) as HTMLElement;

describe('SetupChecklist', () => {
  afterEach(() => localStorage.clear());

  it('shows done and to-do steps with the progress and deep links', async () => {
    setup();
    expect(await screen.findByRole('heading', { name: 'Configurare' })).toBeVisible();
    expect(screen.getByTestId('setup-progress')).toHaveTextContent('5 din 8');
    expect(step('rule')).toHaveClass('is-done');
    expect(within(step('photos')).getByRole('link', { name: 'Adaugă angajat' })).toHaveAttribute(
      'href',
      '/dispozitive',
    );
    // A manager cannot link Telegram (locations.manage): no inline button.
    expect(within(step('alerts')).queryByRole('button', { name: /Telegram/ })).toBeNull();
    expect(
      within(step('alerts')).getByRole('link', { name: 'Activează notificările' }),
    ).toHaveAttribute('href', '/alerte#notificari');
    // No push on this device: the test waits for it.
    expect(within(step('test')).getByRole('button', { name: 'Trimite un test' })).toBeDisabled();
  });

  it('counts staff photos and the location Telegram chat', async () => {
    const api = fakeApi({
      listStaffProfiles: vi.fn(async () => [
        { id: 'p', name: 'Uniformă', description_ro: '', examples: 3, has_centroid: true },
      ]),
      listLocations: vi.fn(async () => [
        { id: 'demo', name: 'Terasa demo', type: 'restaurant', telegram_chat_id: '-100' },
      ]),
    });
    const user = userEvent.setup();
    setup({ api });
    expect(await screen.findByTestId('setup-progress')).toHaveTextContent('7 din 8');
    // One step left: the card is a single line until "Arată".
    expect(screen.getByText('Mai ai 1 pas: Alertă de test trimisă')).toBeInTheDocument();
    expect(step('photos')).toBeNull();
    expect(screen.queryByRole('progressbar')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Arată' }));
    expect(step('photos')).toHaveClass('is-done');
    expect(step('alerts')).toHaveClass('is-done');
  });

  it('a manager can do every remaining step', async () => {
    setup({ role: 'manager', cameras: [], rules: [] });
    await screen.findByRole('heading', { name: 'Configurare' });
    expect(screen.getByTestId('setup-progress')).toHaveTextContent('1 din 8');
    expect(screen.queryByText('cere-i proprietarului')).not.toBeInTheDocument();
  });

  it('a role without a permission sees "cere-i proprietarului"', async () => {
    const me = meAs('manager');
    me.locations = me.locations.map((l) => ({
      ...l,
      permissions: l.permissions.filter((p) => p !== 'devices.manage'),
    }));
    const live = { cameras: [], rules: [], loading: false } as unknown as LiveData;
    render(
      <ApiContext.Provider value={fakeApi()}>
        <AuthContext.Provider value={fakeAuth(me)}>
          <LiveDataContext.Provider value={live}>
            <MemoryRouter>
              <Toaster>
                <SetupChecklist push={fakePush('off')} />
              </Toaster>
            </MemoryRouter>
          </LiveDataContext.Provider>
        </AuthContext.Provider>
      </ApiContext.Provider>,
    );
    await screen.findByRole('heading', { name: 'Configurare' });
    expect(within(step('camera')).getByText('cere-i proprietarului')).toBeVisible();
    expect(within(step('camera')).queryByRole('link')).not.toBeInTheDocument();
    expect(within(step('rule')).getByRole('button', { name: 'Scrie o regulă' })).toBeDisabled();
  });

  it('is never shown to staff', async () => {
    const { api } = setup({ role: 'staff' });
    await waitFor(() => expect(api.listLocations).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole('heading', { name: 'Configurare' })).not.toBeInTheDocument();
    expect(api.listStaffProfiles).not.toHaveBeenCalled();
  });

  it('is gone once every step is done', async () => {
    localStorage.setItem(`aivee.setup.tested.${FAKE_ME.user.id}`, '1');
    const api = fakeApi({
      listStaffProfiles: vi.fn(async () => [
        { id: 'p', name: 'U', description_ro: '', examples: 1, has_centroid: true },
      ]),
    });
    setup({ api, push: fakePush('on') });
    await waitFor(() => expect(api.listStaffProfiles).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole('heading', { name: 'Configurare' })).not.toBeInTheDocument();
  });

  it('collapses, and "Ascunde" is remembered per user', async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByRole('heading', { name: 'Configurare' });
    await user.click(screen.getByRole('button', { name: 'Restrânge' }));
    expect(step('photos')).toBeNull();
    expect(screen.getByRole('button', { name: 'Arată pașii' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    await user.click(screen.getByRole('button', { name: 'Ascunde' }));
    expect(screen.queryByRole('heading', { name: 'Configurare' })).not.toBeInTheDocument();
    expect(localStorage.getItem(`aivee.setup.hidden.${FAKE_ME.user.id}`)).toBe('1');
  });

  it('sends a test push and marks the step done after success', async () => {
    const user = userEvent.setup();
    const { push } = setup({ push: fakePush('on') });
    // Two steps left: the card starts as one line.
    await user.click(await screen.findByRole('button', { name: 'Arată' }));
    const button = screen.getByRole('button', { name: 'Trimite un test' });
    expect(step('alerts')).toHaveClass('is-done');
    await user.click(button);
    expect(push.sendTest).toHaveBeenCalled();
    await waitFor(() => expect(step('test')).toHaveClass('is-done'));
    expect(isTestSent(FAKE_ME.user.id)).toBe(true);
  });

  it('a test that reached nobody stays to do', async () => {
    const user = userEvent.setup();
    setup({ push: fakePush('on', 0) });
    await user.click(await screen.findByRole('button', { name: 'Arată' }));
    await user.click(screen.getByRole('button', { name: 'Trimite un test' }));
    expect(await screen.findByText(/Niciun dispozitiv abonat/)).toBeVisible();
    expect(step('test')).not.toHaveClass('is-done');
    expect(isTestSent(FAKE_ME.user.id)).toBe(false);
  });

  it('offers "Conectează Telegram" inside the alerts step to an owner', async () => {
    setup({ role: 'owner' });
    await screen.findByRole('heading', { name: 'Configurare' });
    expect(
      await within(step('alerts')).findByRole('button', { name: /Conectează Telegram/ }),
    ).toBeInTheDocument();
  });

  it('starts as one line with two steps left, and keeps "Ascunde"', async () => {
    const user = userEvent.setup();
    const api = fakeApi({
      listStaffProfiles: vi.fn(async () => [
        { id: 'p', name: 'U', description_ro: '', examples: 1, has_centroid: true },
      ]),
    });
    setup({ api });
    expect(
      await screen.findByText('Mai ai 2 pași: Alerte pe telefon, Alertă de test trimisă'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Arată' })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: 'Ascunde' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Arată' }));
    expect(step('alerts')).not.toBeNull();
    expect(screen.queryByText(/^Mai ai/)).toBeNull();
  });
});
