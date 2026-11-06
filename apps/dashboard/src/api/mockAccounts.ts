// In-browser accounts for the mock API: three demo users, two locations, invites, an append-only
// audit log and the alert lifecycle (acknowledge → arrive). Mirrors
// docs/plans/2026-11-06-auth-roles-audit.md closely enough to build the UI before the backend lands.
import type { AlertEvent } from '../contracts';
import {
  ApiError,
  UNAUTHORIZED_EVENT,
  type AlertCase,
  type AuditEntry,
  type AuditPage,
  type AuditQuery,
  type DurationStat,
  type Invite,
  type InviteInfo,
  type Location,
  type Me,
  type Member,
  type Permission,
  type RegisterInput,
  type Role,
  type ServiceMetrics,
} from './client';

/** Password of the three demo users in the mock (the real seed reads DEMO_PASSWORD). */
export const MOCK_PASSWORD = 'demo1234';
export const MOCK_USERS = ['owner@aivee.demo', 'manager@aivee.demo', 'staff@aivee.demo'] as const;
/** Opens /invitatie/demo-invite in the mock. */
export const MOCK_INVITE_TOKEN = 'demo-invite';

const SESSION_KEY = 'aivee.mock.session';
const MIN_PASSWORD = 8;
/** How long the mock waiter takes to reach the table after "Merg eu". */
const ARRIVE_AFTER_MS = 4_000;

export const ROLE_PERMISSIONS: Record<Role, Permission[]> = {
  owner: [
    'alerts.view',
    'alerts.ack',
    'staff.review',
    'staff.enrol',
    'rules.manage',
    'devices.manage',
    'users.manage',
    'locations.manage',
    'audit.view',
  ],
  manager: [
    'alerts.view',
    'alerts.ack',
    'staff.review',
    'staff.enrol',
    'rules.manage',
    'devices.manage',
    'users.manage',
    'audit.view',
  ],
  staff: ['alerts.view', 'alerts.ack', 'audit.view.own'],
};

interface User {
  id: string;
  name: string;
  email: string;
  password: string;
  orgId: string;
  isOwner: boolean;
}
interface Membership {
  locationId: string;
  userId: string;
  role: Exclude<Role, 'owner'>;
}
interface PendingInvite {
  location_id: string;
  role: Role;
  email: string;
  expires_at: string;
}

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const seconds = (a: string | null, b: string | null) =>
  a && b ? Math.max(0, Math.round((Date.parse(b) - Date.parse(a)) / 1000)) : null;
let seq = 0;
const uid = (p: string) => `${p}-${Date.now().toString(36)}-${(seq++).toString(36)}`;

const unauthenticated = () => {
  window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  return new ApiError('Sesiunea a expirat. Intră din nou în cont.', 'unauthenticated', 401);
};
const forbidden = (msg = 'Nu ai dreptul să faci asta.') => new ApiError(msg, 'forbidden', 403);
const notFound = () => new ApiError('Resursa nu există.', 'not_found', 404);

/** Hidden history used only for the service statistics, so the metrics page has a shape. */
const HISTORY: [wait: number, reaction: number, travel: number][] = [
  [95, 40, 35],
  [130, 55, 50],
  [70, 25, 30],
  [210, 120, 60],
  [88, 30, 41],
  [150, 70, 52],
  [64, 20, 33],
  [180, 95, 58],
  [110, 45, 47],
  [75, 28, 36],
  [260, 160, 70],
  [99, 38, 44],
];

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? (s[m] ?? 0) : Math.round(((s[m - 1] ?? 0) + (s[m] ?? 0)) / 2);
}
function p90(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.ceil(s.length * 0.9) - 1)] ?? null;
}
const stat = (xs: number[]): DurationStat => ({
  median_s: median(xs),
  p90_s: p90(xs),
  count: xs.length,
});

export class MockAccounts {
  private orgs = new Map([['org-demo', 'AiVee Demo']]);
  private users: User[] = [
    {
      id: 'u-owner',
      name: 'Ioana Popescu',
      email: 'owner@aivee.demo',
      password: MOCK_PASSWORD,
      orgId: 'org-demo',
      isOwner: true,
    },
    {
      id: 'u-manager',
      name: 'Mihai Ionescu',
      email: 'manager@aivee.demo',
      password: MOCK_PASSWORD,
      orgId: 'org-demo',
      isOwner: false,
    },
    {
      id: 'u-staff',
      name: 'Ana Dumitru',
      email: 'staff@aivee.demo',
      password: MOCK_PASSWORD,
      orgId: 'org-demo',
      isOwner: false,
    },
  ];
  private locations: (Location & { orgId: string })[] = [
    { id: 'demo', name: 'Terasa demo', type: 'restaurant', orgId: 'org-demo' },
    { id: 'centru', name: 'Bistro Centru', type: 'restaurant', orgId: 'org-demo' },
  ];
  private members: Membership[] = [
    { locationId: 'demo', userId: 'u-manager', role: 'manager' },
    { locationId: 'demo', userId: 'u-staff', role: 'staff' },
  ];
  private invites = new Map<string, PendingInvite>([
    [
      MOCK_INVITE_TOKEN,
      {
        location_id: 'demo',
        role: 'staff',
        email: 'nou@aivee.demo',
        expires_at: new Date(Date.now() + 7 * 86_400_000).toISOString(),
      },
    ],
  ]);
  private audit: AuditEntry[] = seedAudit();
  /** event_id → who pressed "Merg eu" and when; arrival time once the waiter reached the zone. */
  private acks = new Map<
    string,
    { at: string; by: string; by_id: string; arrived_at: string | null }
  >([['e-1', { at: ago(47.5), by: 'Ana Dumitru', by_id: 'u-staff', arrived_at: ago(46.2) }]]);
  private userId: string | null = null;

  constructor(
    private readonly events: () => AlertEvent[],
    private readonly zoneName: (zoneId: string) => string,
    private readonly onArrived: (c: AlertCase) => void,
  ) {
    try {
      this.userId = localStorage.getItem(SESSION_KEY);
    } catch {
      this.userId = null;
    }
    if (!this.users.some((u) => u.id === this.userId)) this.userId = null;
  }

  // --- session -------------------------------------------------------------------------------

  private persist() {
    try {
      if (this.userId) localStorage.setItem(SESSION_KEY, this.userId);
      else localStorage.removeItem(SESSION_KEY);
    } catch {
      /* in-memory only */
    }
  }

  private current(): User {
    const u = this.users.find((x) => x.id === this.userId);
    if (!u) throw unauthenticated();
    return u;
  }

  private meOf(u: User): Me {
    const locations = u.isOwner
      ? this.locations
          .filter((l) => l.orgId === u.orgId)
          .map((l) => ({
            id: l.id,
            name: l.name,
            type: l.type,
            role: 'owner' as Role,
            permissions: [...ROLE_PERMISSIONS.owner],
          }))
      : this.members
          .filter((m) => m.userId === u.id)
          .flatMap((m) => {
            const l = this.locations.find((x) => x.id === m.locationId);
            return l
              ? [
                  {
                    id: l.id,
                    name: l.name,
                    type: l.type,
                    role: m.role,
                    permissions: [...ROLE_PERMISSIONS[m.role]],
                  },
                ]
              : [];
          });
    return {
      user: { id: u.id, name: u.name, email: u.email },
      org: { id: u.orgId, name: this.orgs.get(u.orgId) ?? '' },
      is_owner: u.isOwner,
      locations,
    };
  }

  private roleAt(locationId: string): Role | null {
    const u = this.current();
    const loc = this.locations.find((l) => l.id === locationId && l.orgId === u.orgId);
    if (!loc) return null;
    if (u.isOwner) return 'owner';
    return this.members.find((m) => m.userId === u.id && m.locationId === locationId)?.role ?? null;
  }

  private require(permission: Permission, locationId: string): Role {
    const role = this.roleAt(locationId);
    if (!role) throw notFound();
    if (!ROLE_PERMISSIONS[role].includes(permission)) throw forbidden();
    return role;
  }

  private log(entry: Omit<AuditEntry, 'id' | 'at' | 'before' | 'after'> & Partial<AuditEntry>) {
    this.audit.unshift({
      id: uid('a'),
      at: new Date().toISOString(),
      before: null,
      after: null,
      ...entry,
    });
  }

  private actor() {
    const u = this.current();
    return { kind: 'user' as const, id: u.id, name: u.name };
  }

  me(): Me {
    return this.meOf(this.current());
  }

  login(email: string, password: string): Me {
    const u = this.users.find((x) => x.email === email.trim().toLowerCase());
    if (!u || u.password !== password) {
      this.log({
        location_id: null,
        actor: { kind: 'system', id: 'auth', name: 'Sistem' },
        kind: 'auth.login_failed',
        target: null,
        summary_ro: `Încercare de autentificare eșuată pentru ${email.trim()}`,
      });
      throw new ApiError('Email sau parolă greșită.', 'invalid_credentials', 401);
    }
    this.userId = u.id;
    this.persist();
    this.log({
      location_id: null,
      actor: this.actor(),
      kind: 'auth.login',
      target: null,
      summary_ro: `${u.name} a intrat în cont`,
    });
    return this.meOf(u);
  }

  register(input: RegisterInput): Me {
    const email = input.email.trim().toLowerCase();
    if (this.users.some((u) => u.email === email)) {
      throw new ApiError('Există deja un cont cu acest email.', 'email_taken', 409);
    }
    if (input.password.length < MIN_PASSWORD) {
      throw new ApiError(`Parola are nevoie de minim ${MIN_PASSWORD} caractere.`, 'invalid', 422);
    }
    const orgId = uid('org');
    this.orgs.set(orgId, input.org_name.trim());
    const u: User = {
      id: uid('u'),
      name: input.name.trim(),
      email,
      password: input.password,
      orgId,
      isOwner: true,
    };
    this.users.push(u);
    this.userId = u.id;
    this.persist();
    return this.meOf(u);
  }

  logout() {
    if (this.userId) {
      this.log({
        location_id: null,
        actor: this.actor(),
        kind: 'auth.logout',
        target: null,
        summary_ro: `${this.current().name} a ieșit din cont`,
      });
    }
    this.userId = null;
    this.persist();
  }

  getInvite(token: string): InviteInfo {
    const inv = this.invites.get(token);
    if (!inv || Date.parse(inv.expires_at) < Date.now()) {
      throw new ApiError('Invitația nu mai este valabilă.', 'invite_invalid', 404);
    }
    const loc = this.locations.find((l) => l.id === inv.location_id);
    return {
      org_name: this.orgs.get(loc?.orgId ?? '') ?? '',
      location_name: loc?.name ?? inv.location_id,
      role: inv.role,
      email: inv.email,
    };
  }

  acceptInvite(token: string, input: { name: string; password: string }): Me {
    const info = this.getInvite(token);
    const inv = this.invites.get(token) as PendingInvite;
    if (input.password.length < MIN_PASSWORD) {
      throw new ApiError(`Parola are nevoie de minim ${MIN_PASSWORD} caractere.`, 'invalid', 422);
    }
    const loc = this.locations.find((l) => l.id === inv.location_id);
    const u: User = {
      id: uid('u'),
      name: input.name.trim(),
      email: info.email,
      password: input.password,
      orgId: loc?.orgId ?? 'org-demo',
      isOwner: false,
    };
    this.users.push(u);
    this.members.push({
      locationId: inv.location_id,
      userId: u.id,
      role: inv.role === 'owner' ? 'manager' : inv.role,
    });
    this.invites.delete(token);
    this.userId = u.id;
    this.persist();
    this.log({
      location_id: inv.location_id,
      actor: this.actor(),
      kind: 'user.joined',
      target: { type: 'user', id: u.id, label: u.name },
      summary_ro: `${u.name} s-a alăturat echipei din ${info.location_name}`,
    });
    return this.meOf(u);
  }

  // --- locations and members -----------------------------------------------------------------

  listLocations(): Location[] {
    return this.me().locations.map(({ id, name, type }) => ({
      id,
      name,
      type,
      telegram_chat_id: this.locations.find((l) => l.id === id)?.telegram_chat_id ?? null,
    }));
  }

  createLocation(input: Location): Location {
    const u = this.current();
    if (!u.isOwner) throw forbidden('Doar proprietarul poate adăuga locații.');
    if (!/^[a-z0-9-]{2,40}$/.test(input.id)) {
      throw new ApiError('Id-ul poate avea litere mici, cifre și cratimă (2–40).', 'invalid', 422);
    }
    if (this.locations.some((l) => l.id === input.id)) {
      throw new ApiError('Există deja o locație cu acest id.', 'conflict', 409);
    }
    const loc = { ...input, orgId: u.orgId };
    this.locations.push(loc);
    this.log({
      location_id: loc.id,
      actor: this.actor(),
      kind: 'location.created',
      target: { type: 'location', id: loc.id, label: loc.name },
      summary_ro: `${u.name} a adăugat locația ${loc.name}`,
      after: input,
    });
    return input;
  }

  updateLocation(id: string, patch: Partial<Omit<Location, 'id'>>): Location {
    this.require('locations.manage', id);
    const loc = this.locations.find((l) => l.id === id) as Location & { orgId: string };
    const before = {
      name: loc.name,
      type: loc.type,
      telegram_chat_id: loc.telegram_chat_id ?? null,
    };
    Object.assign(loc, patch);
    this.log({
      location_id: id,
      actor: this.actor(),
      kind: 'location.updated',
      target: { type: 'location', id, label: loc.name },
      summary_ro: `${this.current().name} a modificat locația ${loc.name}`,
      before,
      after: { name: loc.name, type: loc.type, telegram_chat_id: loc.telegram_chat_id ?? null },
    });
    return { id, name: loc.name, type: loc.type, telegram_chat_id: loc.telegram_chat_id ?? null };
  }

  deleteLocation(id: string) {
    this.require('locations.manage', id);
    const loc = this.locations.find((l) => l.id === id);
    this.locations = this.locations.filter((l) => l.id !== id);
    this.members = this.members.filter((m) => m.locationId !== id);
    this.log({
      location_id: null,
      actor: this.actor(),
      kind: 'location.deleted',
      target: { type: 'location', id, label: loc?.name ?? id },
      summary_ro: `${this.current().name} a șters locația ${loc?.name ?? id}`,
    });
  }

  listMembers(locationId: string): Member[] {
    this.require('users.manage', locationId);
    const orgId = this.current().orgId;
    // Like the API: the org's owners are listed too, with role "owner" (read-only in the UI).
    const owners: Member[] = this.users
      .filter((u) => u.orgId === orgId && u.isOwner)
      .map((u) => ({ user_id: u.id, name: u.name, email: u.email, role: 'owner' }));
    return [
      ...owners,
      ...this.members
        .filter((m) => m.locationId === locationId)
        .map((m) => {
          const u = this.users.find((x) => x.id === m.userId) as User;
          return { user_id: u.id, name: u.name, email: u.email, role: m.role };
        }),
    ];
  }

  /** Managers may only manage staff of their own location (spec: users.manage). */
  private guardMember(locationId: string, target?: Membership, nextRole?: Role) {
    const role = this.require('users.manage', locationId);
    if (role === 'owner') return;
    if ((target && target.role !== 'staff') || (nextRole && nextRole !== 'staff')) {
      throw forbidden('Doar proprietarul poate gestiona managerii.');
    }
  }

  updateMember(locationId: string, userId: string, role: Role): Member {
    const m = this.members.find((x) => x.locationId === locationId && x.userId === userId);
    if (!m) throw notFound();
    this.guardMember(locationId, m, role);
    if (role === 'owner') throw forbidden('Rolul de proprietar nu se atribuie din echipă.');
    const before = m.role;
    m.role = role;
    const u = this.users.find((x) => x.id === userId) as User;
    this.log({
      location_id: locationId,
      actor: this.actor(),
      kind: 'member.role_changed',
      target: { type: 'user', id: userId, label: u.name },
      summary_ro: `${this.current().name} l-a făcut pe ${u.name} ${role === 'manager' ? 'manager' : 'personal'}`,
      before: { role: before },
      after: { role },
    });
    return { user_id: u.id, name: u.name, email: u.email, role };
  }

  removeMember(locationId: string, userId: string) {
    const m = this.members.find((x) => x.locationId === locationId && x.userId === userId);
    if (!m) throw notFound();
    this.guardMember(locationId, m);
    this.members = this.members.filter((x) => x !== m);
    const u = this.users.find((x) => x.id === userId) as User;
    this.log({
      location_id: locationId,
      actor: this.actor(),
      kind: 'member.removed',
      target: { type: 'user', id: userId, label: u.name },
      summary_ro: `${this.current().name} l-a scos pe ${u.name} din echipă`,
    });
  }

  createInvite(input: { location_id: string; role: Role; email: string }): Invite {
    this.guardMember(input.location_id, undefined, input.role);
    if (input.role === 'owner')
      throw forbidden('Rolul de proprietar nu se atribuie prin invitație.');
    const token = uid('inv');
    const expires_at = new Date(Date.now() + 7 * 86_400_000).toISOString();
    this.invites.set(token, { ...input, expires_at });
    this.log({
      location_id: input.location_id,
      actor: this.actor(),
      kind: 'user.invited',
      target: { type: 'invite', id: token, label: input.email },
      summary_ro: `${this.current().name} l-a invitat pe ${input.email} ca ${input.role === 'manager' ? 'manager' : 'personal'}`,
    });
    return { invite_url: `${window.location.origin}/invitatie/${token}`, expires_at };
  }

  // --- audit ---------------------------------------------------------------------------------

  listAudit(q: AuditQuery): AuditPage {
    const role = this.roleAt(q.location_id);
    if (!role) throw notFound();
    const me = this.current();
    const own = !ROLE_PERMISSIONS[role].includes('audit.view');
    const limit = q.limit ?? 50;
    // Like the API: "rule" matches every rule.* kind, "rule.updated" only itself.
    const kindMatch = (k: string) => !q.kind || k === q.kind || k.startsWith(`${q.kind}.`);
    const cursor = q.before ? this.audit.find((e) => e.id === q.before)?.at : undefined;
    const rows = this.audit
      .filter(
        (e) => e.location_id === q.location_id || (e.location_id === null && role === 'owner'),
      )
      .filter((e) => (own ? e.actor.id === me.id : true))
      .filter((e) => (q.actor ? e.actor.id === q.actor : true))
      .filter((e) => kindMatch(e.kind))
      .filter((e) => (cursor ? e.at < cursor : true))
      .filter((e) => (q.from ? e.at >= q.from : true))
      .filter((e) => (q.to ? e.at < q.to : true))
      .sort((a, b) => b.at.localeCompare(a.at));
    const items = rows.slice(0, limit);
    return {
      items,
      next_before: rows.length > limit ? (items[items.length - 1]?.id ?? null) : null,
    };
  }

  // --- alert lifecycle -----------------------------------------------------------------------

  /** Fold the mock's events with the acknowledgements into one row per alert, newest first. */
  cases(locationId: string): AlertCase[] {
    const open = new Map<string, AlertCase>();
    const out: AlertCase[] = [];
    const sorted = [...this.events()].sort((a, b) => a.at.localeCompare(b.at));
    for (const e of sorted) {
      const key = `${e.camera_id}|${e.rule_id}|${e.zone_id}`;
      const state = e.state as string;
      if (state === 'opened') {
        if (open.has(key)) continue;
        const c: AlertCase = {
          event_id: e.event_id,
          rule_id: e.rule_id,
          location_id: locationId,
          camera_id: e.camera_id,
          zone_id: e.zone_id,
          zone_name: this.zoneName(e.zone_id),
          summary_ro: e.summary_ro,
          opened_at: e.at,
          acknowledged_at: null,
          acknowledged_by: null,
          acknowledged_by_id: null,
          arrived_at: null,
          unacknowledged_arrival: false,
          closed_at: null,
          wait_s: null,
          reaction_s: null,
          travel_s: null,
        };
        open.set(key, c);
        out.push(c);
      } else if (state === 'arrived') {
        const c = open.get(key);
        if (c && !c.arrived_at) c.arrived_at = e.at;
      } else if (state === 'closed') {
        const c = open.get(key);
        if (c) {
          c.closed_at = e.at;
          open.delete(key);
        }
      }
    }
    for (const c of out) {
      const ack = this.acks.get(c.event_id);
      if (ack) {
        c.acknowledged_at = ack.at;
        c.acknowledged_by = ack.by;
        c.acknowledged_by_id = ack.by_id;
        c.arrived_at ??= ack.arrived_at;
      }
      c.unacknowledged_arrival = !!c.arrived_at && !c.acknowledged_at;
      c.wait_s = seconds(c.opened_at, c.arrived_at ?? c.closed_at);
      c.reaction_s = seconds(c.opened_at, c.acknowledged_at);
      c.travel_s = seconds(c.acknowledged_at, c.arrived_at);
    }
    return out.reverse();
  }

  listAlertCases(q: { location_id: string; state?: string; limit?: number }): AlertCase[] {
    this.require('alerts.view', q.location_id);
    const rows = this.cases(q.location_id).filter((c) =>
      !q.state ? true : q.state === 'open' ? c.closed_at === null : c.closed_at !== null,
    );
    return rows.slice(0, q.limit ?? 100);
  }

  ackAlert(eventId: string, locationId: string): AlertCase {
    this.require('alerts.ack', locationId);
    const c = this.cases(locationId).find((x) => x.event_id === eventId);
    if (!c) throw notFound();
    if (c.closed_at) throw new ApiError('Alerta e deja închisă.', 'conflict', 409);
    if (c.acknowledged_by) {
      throw new ApiError(`${c.acknowledged_by} a preluat deja alerta.`, 'conflict', 409);
    }
    const me = this.current();
    this.acks.set(eventId, {
      at: new Date().toISOString(),
      by: me.name,
      by_id: me.id,
      arrived_at: null,
    });
    this.log({
      location_id: locationId,
      actor: this.actor(),
      kind: 'alert.acknowledged',
      target: { type: 'alert', id: eventId, label: c.zone_name },
      summary_ro: `${me.name} a preluat alerta de la ${c.zone_name}`,
    });
    setTimeout(() => {
      const ack = this.acks.get(eventId);
      if (!ack || ack.arrived_at) return;
      ack.arrived_at = new Date().toISOString();
      const now = this.cases(locationId).find((x) => x.event_id === eventId);
      this.log({
        location_id: locationId,
        actor: { kind: 'device', id: 'edge-sala', name: 'edge-sala' },
        kind: 'alert.arrived',
        target: { type: 'alert', id: eventId, label: c.zone_name },
        summary_ro: `${me.name} a ajuns la ${c.zone_name}`,
      });
      if (now) this.onArrived(now);
    }, ARRIVE_AFTER_MS);
    return this.cases(locationId).find((x) => x.event_id === eventId) as AlertCase;
  }

  serviceMetrics(q: { location_id: string; from?: string; to?: string }): ServiceMetrics {
    this.require('alerts.view', q.location_id);
    const cases = this.cases(q.location_id).filter((c) => c.closed_at || c.arrived_at);
    const pick = (f: (c: AlertCase) => number | null, i: 0 | 1 | 2) => [
      ...cases.map(f).filter((x): x is number => x !== null),
      ...HISTORY.map((h) => h[i]),
    ];
    return {
      location_id: q.location_id,
      from: q.from ?? null,
      to: q.to ?? null,
      alerts: cases.length + HISTORY.length,
      wait: stat(pick((c) => c.wait_s, 0)),
      reaction: stat(pick((c) => c.reaction_s, 1)),
      travel: stat(pick((c) => c.travel_s, 2)),
    };
  }
}

function seedAudit(): AuditEntry[] {
  const owner = { kind: 'user' as const, id: 'u-owner', name: 'Ioana Popescu' };
  const manager = { kind: 'user' as const, id: 'u-manager', name: 'Mihai Ionescu' };
  const staff = { kind: 'user' as const, id: 'u-staff', name: 'Ana Dumitru' };
  const edge = { kind: 'device' as const, id: 'edge-sala', name: 'edge-sala' };
  const rows: Omit<AuditEntry, 'id'>[] = [
    {
      at: ago(46),
      location_id: 'demo',
      actor: edge,
      kind: 'alert.closed',
      target: { type: 'alert', id: 'e-1', label: 'Masa 1' },
      summary_ro: 'Alerta de la Masa 1 s-a închis',
      before: null,
      after: null,
    },
    {
      at: ago(46.2),
      location_id: 'demo',
      actor: edge,
      kind: 'alert.arrived',
      target: { type: 'alert', id: 'e-1', label: 'Masa 1' },
      summary_ro: 'Ana Dumitru a ajuns la Masa 1',
      before: null,
      after: null,
    },
    {
      at: ago(47.5),
      location_id: 'demo',
      actor: staff,
      kind: 'alert.acknowledged',
      target: { type: 'alert', id: 'e-1', label: 'Masa 1' },
      summary_ro: 'Ana Dumitru a preluat alerta de la Masa 1',
      before: null,
      after: null,
    },
    {
      at: ago(48),
      location_id: 'demo',
      actor: edge,
      kind: 'alert.opened',
      target: { type: 'alert', id: 'e-1', label: 'Masa 1' },
      summary_ro: 'Masa 1: nimeni de la personal de 1 minut',
      before: null,
      after: null,
    },
    {
      at: ago(62),
      location_id: 'demo',
      actor: manager,
      kind: 'staff.confirmed',
      target: { type: 'track', id: '7', label: 'angajat #7' },
      summary_ro: 'Mihai Ionescu a confirmat că #7 e din personal',
      before: null,
      after: null,
    },
    {
      at: ago(75),
      location_id: 'demo',
      actor: manager,
      kind: 'rule.updated',
      target: { type: 'rule', id: 'r-neservit', label: 'Masă neservită' },
      summary_ro: 'Mihai Ionescu a schimbat regula „Masă neservită”',
      before: { absent_staff_s: 300 },
      after: { absent_staff_s: 120 },
    },
    {
      at: ago(90),
      location_id: 'demo',
      actor: manager,
      kind: 'zones.updated',
      target: { type: 'camera', id: 'cam-sala', label: 'Sala principală' },
      summary_ro: 'Mihai Ionescu a modificat zonele din Sala principală',
      before: { zones: 2 },
      after: { zones: 3 },
    },
    {
      at: ago(95),
      location_id: 'demo',
      actor: staff,
      kind: 'auth.login',
      target: null,
      summary_ro: 'Ana Dumitru a intrat în cont',
      before: null,
      after: null,
    },
    {
      at: ago(120),
      location_id: 'demo',
      actor: edge,
      kind: 'device.online',
      target: { type: 'device', id: 'edge-sala', label: 'edge-sala' },
      summary_ro: 'Dispozitivul edge-sala e online',
      before: null,
      after: null,
    },
    {
      at: ago(180),
      location_id: 'demo',
      actor: owner,
      kind: 'user.invited',
      target: { type: 'invite', id: 'inv-0', label: 'staff@aivee.demo' },
      summary_ro: 'Ioana Popescu a invitat-o pe staff@aivee.demo ca personal',
      before: null,
      after: null,
    },
    {
      at: ago(200),
      location_id: 'demo',
      actor: owner,
      kind: 'camera.created',
      target: { type: 'camera', id: 'cam-sala', label: 'Sala principală' },
      summary_ro: 'Ioana Popescu a adăugat camera Sala principală',
      before: null,
      after: { source: 'rtsp://…/stream1' },
    },
    {
      at: ago(240),
      location_id: 'demo',
      actor: owner,
      kind: 'location.created',
      target: { type: 'location', id: 'demo', label: 'Terasa demo' },
      summary_ro: 'Ioana Popescu a adăugat locația Terasa demo',
      before: null,
      after: { name: 'Terasa demo', type: 'restaurant' },
    },
    {
      at: ago(300),
      location_id: 'centru',
      actor: owner,
      kind: 'location.created',
      target: { type: 'location', id: 'centru', label: 'Bistro Centru' },
      summary_ro: 'Ioana Popescu a adăugat locația Bistro Centru',
      before: null,
      after: { name: 'Bistro Centru', type: 'restaurant' },
    },
  ];
  return rows.map((r, i) => ({ id: `a-seed-${i}`, ...r }));
}
