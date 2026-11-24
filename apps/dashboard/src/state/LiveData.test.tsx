import { act, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AlertView, CameraView } from '../api/client';
import { ApiContext } from '../api/context';
import { AuthContext } from '../auth/context';
import { fakeApi, fakeAuth } from '../test/fakeApi';
import { useLiveData } from './context';
import { LiveDataProvider } from './LiveData';

const cam: CameraView = {
  id: 'cam-a',
  name: 'Sala',
  source: 'rtsp://x',
  device: 'edge-01',
  online: true,
  zones: [
    {
      id: 'z1',
      name: 'Masa 1',
      tag: 'table',
      polygon: [
        [0, 0],
        [1, 0],
        [1, 1],
      ],
    },
  ],
};

const opened = (over: Partial<AlertView>): AlertView => ({
  event_id: 'e1',
  rule_id: 'r1',
  camera_id: 'cam-a',
  zone_id: 'z1',
  state: 'opened',
  at: new Date().toISOString(),
  summary_ro: 'Masa 1 așteaptă',
  ...over,
});

function Probe() {
  const { alerts, zoneName } = useLiveData();
  return (
    <ul>
      {alerts.map((a) => (
        <li key={a.key}>
          {zoneName(a.zone_id)}:{a.closed_at ? 'închisă' : 'deschisă'}
        </li>
      ))}
    </ul>
  );
}

function setup(overrides: Parameters<typeof fakeApi>[0] = {}) {
  let push: (e: AlertView) => void = () => undefined;
  let reconnect: () => void = () => undefined;
  const api = fakeApi({
    listCameras: vi.fn(async () => [cam]),
    subscribeAlerts: vi.fn((cb) => {
      push = cb;
      return () => undefined;
    }),
    subscribeReconnect: vi.fn((cb) => {
      reconnect = cb;
      return () => undefined;
    }),
    ...overrides,
  });
  render(
    <ApiContext.Provider value={api}>
      <AuthContext.Provider value={fakeAuth()}>
        <LiveDataProvider>
          <Probe />
        </LiveDataProvider>
      </AuthContext.Provider>
    </ApiContext.Provider>,
  );
  return { api, push: (e: AlertView) => act(() => push(e)), reconnect: () => reconnect() };
}

describe('LiveDataProvider', () => {
  it("drops another location's live alerts and keeps this location's", async () => {
    const { api, push } = setup();
    await waitFor(() => expect(api.listCameras).toHaveBeenCalled());
    await waitFor(() => expect(api.getMetrics).toHaveBeenCalled());
    // Folded update of another location; raw row of a camera that is not here.
    push(opened({ event_id: 'x1', location_id: 'bistro', zone_id: 'z9', zone_name: 'Bar' }));
    push(opened({ event_id: 'x2', camera_id: 'cam-other', zone_id: 'z8' }));
    push(opened({ event_id: 'e1' }));
    expect(await screen.findByText('Masa 1:deschisă')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
  });

  it('names a zone that is no longer drawn from the alert, never by its raw id', async () => {
    const { api, push } = setup();
    await waitFor(() => expect(api.getMetrics).toHaveBeenCalled());
    push(opened({ event_id: 'e2', zone_id: 'z-gone', location_id: 'demo', zone_name: 'Masa 7' }));
    push(opened({ event_id: 'e3', zone_id: 'z-lost', rule_id: 'r2' }));
    expect(await screen.findByText('Masa 7:deschisă')).toBeInTheDocument();
    expect(screen.getByText('Zonă ștearsă:deschisă')).toBeInTheDocument();
    expect(screen.queryByText(/z-lost/)).toBeNull();
  });

  it('reads alerts again after the socket reconnects, so a missed close lands', async () => {
    const open = opened({ event_id: 'e1', at: '2026-11-23T10:00:00Z' });
    const closed = { ...open, event_id: 'e1c', state: 'closed', at: '2026-11-23T10:02:00Z' };
    const listAlerts = vi
      .fn()
      .mockResolvedValueOnce([open])
      .mockResolvedValue([closed, open] as AlertView[]);
    const { reconnect } = setup({ listAlerts });
    expect(await screen.findByText('Masa 1:deschisă')).toBeInTheDocument();
    reconnect();
    expect(await screen.findByText('Masa 1:închisă')).toBeInTheDocument();
  });

  it('reads alerts again when the tab becomes visible', async () => {
    const listAlerts = vi.fn(async () => [] as AlertView[]);
    setup({ listAlerts });
    await waitFor(() => expect(listAlerts).toHaveBeenCalledTimes(1));
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(listAlerts).toHaveBeenCalledTimes(2));
  });

  it('closes an alert the lifecycle says is closed', async () => {
    const open = opened({ event_id: 'e1', at: '2026-11-23T10:00:00Z' });
    setup({
      listAlerts: vi.fn(async () => [open]),
      listAlertCases: vi.fn(async () => [
        {
          event_id: 'e1',
          rule_id: 'r1',
          location_id: 'demo',
          camera_id: 'cam-a',
          zone_id: 'z1',
          zone_name: 'Masa 1',
          summary_ro: '',
          opened_at: open.at,
          acknowledged_at: null,
          acknowledged_by: null,
          acknowledged_by_id: null,
          arrived_at: null,
          unacknowledged_arrival: false,
          closed_at: '2026-11-23T10:04:00Z',
          wait_s: 240,
          reaction_s: null,
          travel_s: null,
        },
      ]),
    });
    expect(await screen.findByText('Masa 1:închisă')).toBeInTheDocument();
  });
});
