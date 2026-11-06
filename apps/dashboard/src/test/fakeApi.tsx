import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router';
import { vi } from 'vitest';
import { ApiError, type ApiClient, type Me } from '../api/client';
import { ROLE_PERMISSIONS } from '../api/mockAccounts';
import { ApiContext } from '../api/context';
import { AuthContext, type AuthState } from '../auth/context';
import { Toaster } from '../ui/Toaster';

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
    liveMjpegUrl: vi.fn(() => null),
    pushFrame: vi.fn(async () => undefined),
    captureFrame: vi.fn(async () => {
      throw new ApiError('Nu există încă o imagine de la această cameră.', 'not_found', 404);
    }),
    saveZones: vi.fn(async (_id, zones) => ({ zones, warnings_ro: [] })),
    deleteCamera: vi.fn(async () => undefined),
    listRules: vi.fn(async () => []),
    draftRuleFromText: vi.fn(),
    createRule: vi.fn(async (r) => r),
    updateRule: vi.fn(async (id, patch) => ({ ...patch, id }) as never),
    deleteRule: vi.fn(async () => undefined),
    getRuleStats: vi.fn(async () => ({ days: [], rules: [] })),
    updateCamera: vi.fn(async (id, patch) => ({ ...patch, id }) as never),
    listAlerts: vi.fn(async () => []),
    subscribeAlerts: vi.fn(noop),
    listSuggestions: vi.fn(async () => []),
    subscribeSuggestions: vi.fn(noop),
    subscribeDetections: vi.fn(noop),
    confirmSuggestion: vi.fn(async () => undefined),
    rejectSuggestion: vi.fn(async () => undefined),
    uploadStaffPhoto: vi.fn(async () => undefined),
    listStaffProfiles: vi.fn(async () => []),
    captureStaff: vi.fn(async () => ({
      token: 't',
      camera_id: 'cam1',
      frames: 0,
      candidates: [],
      expires_in_s: 600,
    })),
    confirmStaffCapture: vi.fn(async () => {
      throw new Error('not stubbed');
    }),
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
    createTelegramLink: vi.fn(),
    getTelegramStatus: vi.fn(async () => ({ connected: false, chat_title: null })),
    listMembers: vi.fn(async () => []),
    updateMember: vi.fn(),
    removeMember: vi.fn(async () => undefined),
    createInvite: vi.fn(),
    listInvites: vi.fn(async () => []),
    revokeInvite: vi.fn(async () => undefined),
    listAudit: vi.fn(async () => ({ items: [], next_before: null })),
    listAlertCases: vi.fn(async () => []),
    ackAlert: vi.fn(),
    getServiceMetrics: vi.fn(),
    getServiceHeatmap: vi.fn(async () => ({
      location_id: null,
      from: null,
      to: null,
      timezone: 'Europe/Bucharest',
      cells: [],
    })),
    uploadVideo: vi.fn(),
    listVideos: vi.fn(async () => []),
    getVideo: vi.fn(),
    videoEvents: vi.fn(async () => []),
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
          <MemoryRouter>
            <Toaster>{ui}</Toaster>
          </MemoryRouter>
        </AuthContext.Provider>
      </ApiContext.Provider>,
    ),
  };
}
