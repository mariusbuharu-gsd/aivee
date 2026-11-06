import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ServiceMetrics } from '../api/client';
import type { Rule } from '../contracts';
import { fakeApi, renderWithApi } from '../test/fakeApi';
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

  it('draws no target line without such a rule', async () => {
    renderWithApi(<MetricsPage />, fakeApi({ getServiceMetrics: vi.fn(async () => metrics(60)) }));
    expect(await screen.findByText(/la fel ca în cele 7 zile dinainte/)).toBeInTheDocument();
    await screen.findAllByRole('listitem', { name: /cea mai lentă/ });
    expect(screen.queryByText(/ținta ta/)).not.toBeInTheDocument();
  });
});
