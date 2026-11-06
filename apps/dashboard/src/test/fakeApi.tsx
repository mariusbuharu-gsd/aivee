import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router';
import { vi } from 'vitest';
import type { ApiClient } from '../api/client';
import { ApiContext } from '../api/context';

const noop = () => () => undefined;

export function fakeApi(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    kind: 'mock',
    listCameras: vi.fn(async () => []),
    listDevices: vi.fn(async () => []),
    saveZones: vi.fn(async (_id, zones) => zones),
    listRules: vi.fn(async () => []),
    createRuleFromText: vi.fn(),
    listAlerts: vi.fn(async () => []),
    subscribeAlerts: vi.fn(noop),
    listSuggestions: vi.fn(async () => []),
    subscribeSuggestions: vi.fn(noop),
    subscribeDetections: vi.fn(noop),
    confirmSuggestion: vi.fn(async () => undefined),
    rejectSuggestion: vi.fn(async () => undefined),
    uploadStaffPhoto: vi.fn(async () => undefined),
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

export function renderWithApi(ui: ReactElement, api: ApiClient = fakeApi()) {
  return {
    api,
    ...render(
      <ApiContext.Provider value={api}>
        <MemoryRouter>{ui}</MemoryRouter>
      </ApiContext.Provider>,
    ),
  };
}
