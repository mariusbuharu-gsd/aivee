import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router';
import { vi } from 'vitest';
import type { ApiClient, Me } from '../api/client';
import { ROLE_PERMISSIONS } from '../api/mockAccounts';
import { ApiContext } from '../api/context';
import { AuthContext, type AuthState } from '../auth/context';

const noop = () => () => undefined;

export const FAKE_ME: Me = {
  user: { id: 'u-1', name: 'Ana', email: 'ana@aivee.demo' },
  org: { id: 'o-1', name: 'AiVee Demo' },
  is_owner: false,
  locations: [
    {
      id: 'demo',
      name: 'Terasa demo',
      type: 'restaurant',
      role: 'manager',
      permissions: ROLE_PERMISSIONS.manager,
    },
  ],
};

export function fakeApi(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    kind: 'mock',
    listCameras: vi.fn(async () => []),
    createCamera: vi.fn(async (c) => ({ ...c, zones: [], online: false })),
    listDevices: vi.fn(async () => []),
    saveZones: vi.fn(async (_id, zones) => zones),
    listRules: vi.fn(async () => []),
    draftRuleFromText: vi.fn(),
    createRule: vi.fn(async (r) => r),
    listAlerts: vi.fn(async () => []),
    subscribeAlerts: vi.fn(noop),
    listSuggestions: vi.fn(async () => []),
    subscribeSuggestions: vi.fn(noop),
    subscribeDetections: vi.fn(noop),
    confirmSuggestion: vi.fn(async () => undefined),
    rejectSuggestion: vi.fn(async () => undefined),
    uploadStaffPhoto: vi.fn(async () => undefined),
    me: vi.fn(async () => FAKE_ME),
    login: vi.fn(async () => FAKE_ME),
    register: vi.fn(async () => FAKE_ME),
    logout: vi.fn(async () => undefined),
    getInvite: vi.fn(),
    acceptInvite: vi.fn(async () => FAKE_ME),
    setLocation: vi.fn(),
    listLocations: vi.fn(async () => []),
    createLocation: vi.fn(async (l) => l),
    updateLocation: vi.fn(),
    deleteLocation: vi.fn(async () => undefined),
    listMembers: vi.fn(async () => []),
    updateMember: vi.fn(),
    removeMember: vi.fn(async () => undefined),
    createInvite: vi.fn(),
    listAudit: vi.fn(async () => ({ items: [], next_before: null })),
    listAlertCases: vi.fn(async () => []),
    ackAlert: vi.fn(),
    getServiceMetrics: vi.fn(),
    getMetrics: vi.fn(async () => ({
      devices: [],
      devices_online: 0,
      devices_total: 0,
      events_today: 0,
      alert_latency_ms: null,
    })),
    ...overrides,
  };
}

/** A signed-in manager at the fake location, so components that call `can()` render fully. */
export function fakeAuth(me: Me = FAKE_ME): AuthState {
  const location = me.locations[0] ?? null;
  const done = () => Promise.resolve();
  return {
    status: 'authed',
    me,
    location,
    setLocation: () => undefined,
    can: (p) => location?.permissions.includes(p) ?? false,
    login: done,
    register: done,
    acceptInvite: done,
    logout: done,
    refresh: done,
  };
}

export function renderWithApi(ui: ReactElement, api: ApiClient = fakeApi()) {
  return {
    api,
    ...render(
      <ApiContext.Provider value={api}>
        <AuthContext.Provider value={fakeAuth()}>
          <MemoryRouter>{ui}</MemoryRouter>
        </AuthContext.Provider>
      </ApiContext.Provider>,
    ),
  };
}
