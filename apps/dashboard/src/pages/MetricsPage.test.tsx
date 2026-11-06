import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import type { Me, MeLocation, ServiceMetrics } from '../api/client';
import { ApiContext } from '../api/context';
import { ROLE_PERMISSIONS } from '../api/mockAccounts';
import { AuthContext } from '../auth/context';
import type { Rule } from '../contracts';
import { FAKE_ME, fakeApi, fakeAuth, renderWithApi } from '../test/fakeApi';
import { MetricsPage } from './MetricsPage';

const stat = (median_s: number | null) => ({ median_s, p90_s: median_s, count: 5 });
const metrics = (wait: number | null): ServiceMetrics => ({
  location_id: 'demo',
  from: null,
  to: null,
  alerts: 5,
  wait: stat(wait),
  reaction: stat(40),
  travel: stat(50),
});

const UNSERVED: Rule = {
  id: 'r-neservit',
  camera_id: 'cam',
  name: 'Masă neservită',
  prompt_ro: '',
  zone_tag: 'table',
  all_of: [{ kind: 'absent', role: 'staff', min_duration_s: 90 }],
  action: { type: 'push' },
  enabled: true,
};

describe('MetricsPage', () => {
  it('says the conclusion and draws the target from the unserved-table rule', async () => {
    // Current period: open-ended (no `to`); everything bounded is earlier or a single day.
    const getServiceMetrics = vi.fn(async (q: { to?: string }) => metrics(q.to ? 122 : 104));
    renderWithApi(
      <MetricsPage />,
      fakeApi({ getServiceMetrics, listRules: vi.fn(async () => [UNSERVED]) }),
    );
    expect(
      await screen.findByText(/cu 18 s mai puțin decât în cele 7 zile dinainte/),
    ).toBeInTheDocument();
    expect(screen.getByText('1 min 44 s')).toBeInTheDocument();
    expect(await screen.findByText('ținta ta · 1 min 30 s')).toBeInTheDocument();
    const bars = await screen.findAllByRole('listitem', { name: /peste țintă|cea mai lentă/ });
    expect(bars).toHaveLength(7);
    expect(screen.getByText('Cum citești cifrele').closest('details')).not.toHaveAttribute('open');
  });

  it("uses the location's own target and lets a manager change it", async () => {
    const updateLocation = vi.fn(
      async (id: string, patch: { service_target_s?: number | null }) => ({
        id,
        name: 'Terasa demo',
        type: 'restaurant',
        service_target_s: patch.service_target_s ?? null,
      }),
    );
    renderWithApi(
      <MetricsPage />,
      fakeApi({
        getServiceMetrics: vi.fn(async () => metrics(104)),
        listRules: vi.fn(async () => [UNSERVED]),
        listLocations: vi.fn(async () => [
          { id: 'demo', name: 'Terasa demo', type: 'restaurant', service_target_s: 75 },
        ]),
        updateLocation,
      }),
    );
    expect(await screen.findByText('ținta ta · 1 min 15 s')).toBeInTheDocument();
    expect(screen.queryByText(/timpul din regula/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Schimbă ținta' }));
    const dialog = screen.getByRole('dialog', { name: 'Ținta de servire' });
    const minutes = within(dialog).getByLabelText('Minute');
    const seconds = within(dialog).getByLabelText('Secunde');
    expect(minutes).toHaveValue('1');
    expect(seconds).toHaveValue('15');
    await userEvent.clear(minutes);
    await userEvent.type(minutes, '2');
    await userEvent.clear(seconds);
    await userEvent.click(within(dialog).getByRole('button', { name: 'Salvează' }));
    expect(updateLocation).toHaveBeenCalledWith('demo', { service_target_s: 120 });
    expect(await screen.findByText('ținta ta · 2 min')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps an impossible target from being saved', async () => {
    const updateLocation = vi.fn();
    renderWithApi(
      <MetricsPage />,
      fakeApi({
        getServiceMetrics: vi.fn(async () => metrics(104)),
        listRules: vi.fn(async () => [UNSERVED]),
        updateLocation,
      }),
    );
    await screen.findByText('ținta ta · 1 min 30 s');
    await userEvent.click(screen.getByRole('button', { name: 'Setează ținta' }));
    const dialog = screen.getByRole('dialog', { name: 'Ținta de servire' });
    await userEvent.type(within(dialog).getByLabelText('Secunde'), '75');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Salvează' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent(/între 1 secundă și 60 de minute/);
    expect(updateLocation).not.toHaveBeenCalled();
  });

  it('shows staff the target without the control', async () => {
    const staff: Me = {
      ...FAKE_ME,
      locations: [
        {
          ...(FAKE_ME.locations[0] as MeLocation),
          role: 'staff',
          permissions: ROLE_PERMISSIONS.staff,
        },
      ],
    };
    const api = fakeApi({
      getServiceMetrics: vi.fn(async () => metrics(104)),
      listLocations: vi.fn(async () => [
        { id: 'demo', name: 'Terasa demo', type: 'restaurant', service_target_s: 60 },
      ]),
    });
    render(
      <ApiContext.Provider value={api}>
        <AuthContext.Provider value={fakeAuth(staff)}>
          <MemoryRouter>
            <MetricsPage />
          </MemoryRouter>
        </AuthContext.Provider>
      </ApiContext.Provider>,
    );
    expect(await screen.findByText('ținta ta · 1 min')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /ținta/ })).not.toBeInTheDocument();
  });

  it('draws when guests wait, by weekday and hour', async () => {
    const cells = Array.from({ length: 7 }, () =>
      Array.from({ length: 24 }, () => ({ alerts: 0, wait_median_s: null as number | null })),
    );
    (cells[1] ?? [])[20] = { alerts: 4, wait_median_s: 110 };
    (cells[5] ?? [])[13] = { alerts: 1, wait_median_s: 40 };
    const getServiceHeatmap = vi.fn(async () => ({
      location_id: 'demo',
      from: null,
      to: null,
      timezone: 'Europe/Bucharest',
      cells,
    }));
    renderWithApi(
      <MetricsPage />,
      fakeApi({ getServiceMetrics: vi.fn(async () => metrics(104)), getServiceHeatmap }),
    );
    const heat = await screen.findByRole('figure', { name: 'Când se așteaptă' });
    expect(
      within(heat).getByLabelText('marți 20:00 · 4 alerte · de obicei 1 min 50 s'),
    ).toHaveAttribute('title', 'marți 20:00 · 4 alerte · de obicei 1 min 50 s');
    expect(within(heat).getByLabelText('sâmbătă 13:00 · 1 alertă · de obicei 40 s')).toBeVisible();
    // only the hours with data: 13:00 to 20:00
    expect(within(heat).queryByLabelText(/luni 12:00/)).not.toBeInTheDocument();
    expect(within(heat).getAllByLabelText(/^luni /)).toHaveLength(8);
    const [q] = getServiceHeatmap.mock.calls[0] as unknown as [{ from: string }];
    expect(Date.now() - Date.parse(q.from)).toBeGreaterThan(6 * 86_400_000);
  });

  it('draws no target line without such a rule', async () => {
    renderWithApi(<MetricsPage />, fakeApi({ getServiceMetrics: vi.fn(async () => metrics(60)) }));
    expect(await screen.findByText(/la fel ca în cele 7 zile dinainte/)).toBeInTheDocument();
    await screen.findAllByRole('listitem', { name: /cea mai lentă/ });
    expect(screen.queryByText(/ținta ta/)).not.toBeInTheDocument();
  });
});
