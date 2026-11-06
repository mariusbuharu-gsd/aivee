import { beforeEach, describe, expect, it } from 'vitest';
import { MockApi } from './mock';
import { MOCK_PASSWORD } from './mockAccounts';

beforeEach(() => localStorage.clear());

const signedIn = async (email: string) => {
  const api = new MockApi({ latencyMs: 0, autoplay: false });
  await api.login(email, MOCK_PASSWORD);
  api.setLocation('demo');
  return api;
};

describe('mock accounts follow the permission matrix', () => {
  it('gives the owner every location and staff only their own, with fewer permissions', async () => {
    const owner = await signedIn('owner@aivee.demo');
    expect((await owner.me()).locations.map((l) => l.id)).toEqual(['demo', 'centru']);
    const staff = await signedIn('staff@aivee.demo');
    const me = await staff.me();
    expect(me.locations).toHaveLength(1);
    expect(me.locations[0]?.permissions).toEqual(['alerts.view', 'alerts.ack', 'audit.view.own']);
  });

  it('lets a manager invite staff but not managers', async () => {
    const api = await signedIn('manager@aivee.demo');
    await expect(
      api.createInvite({ location_id: 'demo', role: 'staff', email: 'a@b.ro' }),
    ).resolves.toMatchObject({ invite_url: expect.stringContaining('/invitatie/') });
    await expect(
      api.createInvite({ location_id: 'demo', role: 'manager', email: 'c@d.ro' }),
    ).rejects.toMatchObject({ status: 403 });
  });

  it('shows staff only their own history', async () => {
    const api = await signedIn('staff@aivee.demo');
    const page = await api.listAudit({ location_id: 'demo' });
    expect(page.items.length).toBeGreaterThan(0);
    expect(page.items.every((e) => e.actor.id === 'u-staff')).toBe(true);
  });

  it('lists the org owner among the members, as "owner"', async () => {
    const api = await signedIn('manager@aivee.demo');
    const members = await api.listMembers('demo');
    expect(members.find((m) => m.role === 'owner')?.email).toBe('owner@aivee.demo');
  });

  it('pages the history by entry id and matches a kind family', async () => {
    const api = await signedIn('owner@aivee.demo');
    const first = await api.listAudit({ location_id: 'demo', limit: 3 });
    expect(first.next_before).toBe(first.items[2]?.id);
    const next = await api.listAudit({
      location_id: 'demo',
      limit: 3,
      before: first.next_before ?? '',
    });
    expect((next.items[0]?.at ?? '') <= (first.items[2]?.at ?? '')).toBe(true);
    expect(next.items.some((e) => first.items.some((f) => f.id === e.id))).toBe(false);
    const rules = await api.listAudit({ location_id: 'demo', kind: 'rule' });
    expect(rules.items.length).toBeGreaterThan(0);
    expect(rules.items.every((e) => e.kind.startsWith('rule.'))).toBe(true);
  });

  it('refuses a second "Merg eu" with the name of who took it', async () => {
    const api = await signedIn('staff@aivee.demo');
    api.emitAlert('r-mana', 'z-masa-1', 'opened', 'Masa 1: un client a ridicat mâna');
    const [open] = await api.listAlertCases({ location_id: 'demo', state: 'open' });
    if (!open) throw new Error('expected an open alert');
    const taken = await api.ackAlert(open.event_id);
    expect(taken.acknowledged_by).toBe('Ana Dumitru');
    expect(taken.acknowledged_by_id).toBe('u-staff');
    expect(taken.reaction_s).not.toBeNull();
    await expect(api.ackAlert(open.event_id)).rejects.toMatchObject({ status: 409 });
  });

  it('computes wait, reaction and travel for the seeded alert', async () => {
    const api = await signedIn('manager@aivee.demo');
    const cases = await api.listAlertCases({ location_id: 'demo' });
    const first = cases.find((c) => c.event_id === 'e-1');
    expect(first).toMatchObject({
      reaction_s: 30,
      travel_s: 78,
      wait_s: 108,
      unacknowledged_arrival: false,
    });
    const m = await api.getServiceMetrics({ location_id: 'demo' });
    expect(m.wait.median_s).toBeGreaterThan(0);
    expect(m.wait.count).toBeGreaterThan(0);
  });
});
