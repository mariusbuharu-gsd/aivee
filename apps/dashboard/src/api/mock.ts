// In-browser stand-in for the backend: realistic demo data plus a scripted timeline in which
// alerts open and close, and a "looks like staff" suggestion appears. Used when VITE_API_URL
// is unset, so the dashboard can be built and demoed before the API exists.
import type {
  AlertEvent,
  Condition,
  Detections,
  DeviceStatus,
  Rule,
  StaffSuggestion,
  Zone,
} from '../contracts';
import { MockAccounts } from './mockAccounts';
import {
  ApiError,
  type AlertView,
  type ApiClient,
  type CameraView,
  type DashboardMetrics,
  type Detection,
  type AlertCase,
  type AuditQuery,
  type Location,
  type CameraPatch,
  type NewCamera,
  type SavedZones,
  type RulePatch,
  type RegisterInput,
  type Role,
  type RuleDraft,
  type Unsubscribe,
} from './client';
import { fromContract } from '../live/detections';

const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();
const wait = (ms: number) =>
  ms > 0 ? new Promise<void>((r) => setTimeout(r, ms)) : Promise.resolve();
let seq = 0;
const uid = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(seq++).toString(36)}`;

function seedCameras(): CameraView[] {
  return [
    {
      id: 'cam-sala',
      name: 'Sala principală',
      source: 'rtsp://192.168.1.20:554/stream1',
      device: 'edge-sala',
      online: true,
      zones: [
        {
          id: 'z-masa-1',
          name: 'Masa 1',
          tag: 'table',
          polygon: [
            [0.08, 0.52],
            [0.34, 0.5],
            [0.36, 0.82],
            [0.06, 0.84],
          ],
        },
        {
          id: 'z-masa-2',
          name: 'Masa 2',
          tag: 'table',
          polygon: [
            [0.44, 0.5],
            [0.7, 0.5],
            [0.72, 0.82],
            [0.42, 0.82],
          ],
        },
        {
          id: 'z-intrare',
          name: 'Intrare',
          tag: 'entrance',
          polygon: [
            [0.78, 0.18],
            [0.96, 0.18],
            [0.96, 0.62],
            [0.78, 0.62],
          ],
        },
      ],
    },
    {
      id: 'cam-terasa',
      name: 'Terasă',
      source: 'rtsp://192.168.1.21:554/stream1',
      device: 'edge-terasa',
      online: false,
      zones: [
        {
          id: 'z-masa-3',
          name: 'Masa 3',
          tag: 'table',
          polygon: [
            [0.2, 0.4],
            [0.5, 0.4],
            [0.5, 0.75],
            [0.2, 0.75],
          ],
        },
      ],
    },
  ];
}

function seedRules(): Rule[] {
  return [
    {
      id: 'r-neservit',
      camera_id: 'cam-sala',
      name: 'Masă neservită',
      prompt_ro: 'Anunță ospătarul dacă la o masă nu a venit nimeni de 1 minut',
      zone_tag: 'table',
      all_of: [
        { kind: 'present', role: 'guest', min_duration_s: 60 },
        { kind: 'absent', role: 'staff', min_duration_s: 60 },
      ],
      action: { type: 'telegram', target: null },
      cooldown_s: 300,
      enabled: true,
    },
    {
      id: 'r-mana',
      camera_id: 'cam-sala',
      name: 'Clientul cheamă',
      prompt_ro: 'Spune-mi imediat când cineva ridică mâna la masă',
      zone_tag: 'table',
      all_of: [{ kind: 'pose', role: 'guest', pose: 'raised_hand' }],
      action: { type: 'push', target: null },
      cooldown_s: 60,
      enabled: true,
    },
    {
      id: 'r-pahar',
      camera_id: 'cam-sala',
      name: 'Obiect dispărut',
      prompt_ro: 'Spune-mi dacă dispare un pahar de pe o masă',
      zone_tag: 'table',
      all_of: [{ kind: 'object_gone', role: 'any', objects: ['wine glass'], min_duration_s: 60 }],
      action: { type: 'push', target: null },
      cooldown_s: 300,
      enabled: true,
    },
  ];
}

/**
 * Stand-in snapshots for the mock (the real ones are face-blurred JPEGs from the API): a table
 * seen from above, with or without the wine glass. Colours are the brand's night tokens.
 */
function tableSketch(withGlass: boolean): string {
  const glass = withGlass
    ? '<circle cx="104" cy="44" r="9" fill="none" stroke="#7dd3fc" stroke-width="3"/>'
    : '';
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90">' +
    '<rect width="160" height="90" fill="#1b1d22"/>' +
    '<ellipse cx="80" cy="47" rx="56" ry="28" fill="#23262d" stroke="#e6e8ec" stroke-width="2"/>' +
    '<circle cx="58" cy="48" r="11" fill="none" stroke="#a3a9b4" stroke-width="2"/>' +
    glass +
    '</svg>';
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function seedAlerts(): AlertView[] {
  const ev = (
    id: string,
    rule: string,
    zone: string,
    state: AlertEvent['state'],
    ago: number,
    summary: string,
  ): AlertEvent => ({
    event_id: id,
    rule_id: rule,
    camera_id: 'cam-sala',
    zone_id: zone,
    state,
    at: minutesAgo(ago),
    summary_ro: summary,
    snapshot: true,
  });
  return [
    ev('e-1', 'r-neservit', 'z-masa-1', 'opened', 48, 'Masa 1: nimeni de la personal de 1 minut'),
    ev('e-2', 'r-neservit', 'z-masa-1', 'closed', 46, 'Masa 1: ospătarul a ajuns'),
    ev('e-3', 'r-mana', 'z-masa-2', 'opened', 21, 'Masa 2: un client a ridicat mâna'),
    ev('e-4', 'r-mana', 'z-masa-2', 'closed', 20, 'Masa 2: clientul a fost servit'),
    // An object disappeared from a table, confirmed by the AI check (before/after snapshots).
    // Closed, so the open alerts of the demo timeline stay the first "Merg eu" on the page.
    {
      ...ev('e-5', 'r-pahar', 'z-masa-1', 'opened', 9, 'Masa 1: a dispărut paharul de vin'),
      snapshot_url: tableSketch(false),
      before_snapshot_url: tableSketch(true),
      verification: {
        status: 'confirmed',
        summary_ro: 'Masa 1: a dispărut paharul de vin',
        object_ro: 'pahar de vin',
      },
    },
    ev('e-6', 'r-pahar', 'z-masa-1', 'closed', 7, 'Masa 1: masa a fost verificată'),
  ];
}

/** Very small Romanian keyword parser so the mock returns a plausible rule for any request. */
export function mockRuleFromText(text: string, cameraId: string): Rule {
  const t = text.toLocaleLowerCase('ro');
  const minutes = Number(/(\d+)\s*(?:de\s*)?min/.exec(t)?.[1] ?? '1');
  const seconds = Math.max(0, minutes) * 60;
  let name = 'Masă neservită';
  let zoneTag = 'table';
  let allOf: [Condition, ...Condition[]] = [
    { kind: 'present', role: 'guest', min_duration_s: seconds },
    { kind: 'absent', role: 'staff', min_duration_s: seconds },
  ];
  if (/m[aâ]n[aă]|ridic/.test(t)) {
    name = 'Clientul cheamă';
    allOf = [{ kind: 'pose', role: 'guest', pose: 'raised_hand' }];
  } else if (/coad|intrare|u[sș]/.test(t)) {
    name = 'Coadă la intrare';
    zoneTag = 'entrance';
    const n = Number(/(\d+)\s*(?:de\s*)?(?:persoane|oameni|clien)/.exec(t)?.[1] ?? '3');
    allOf = [
      { kind: 'count', role: 'guest', min_count: Math.max(1, n) },
      { kind: 'absent', role: 'staff', min_duration_s: 0 },
    ];
  } else if (/debaras|pahar|farfur|sticl|strâns|strans/.test(t)) {
    name = 'Masă nedebarasată';
    allOf = [
      {
        kind: 'objects_unattended',
        role: 'any',
        objects: ['cup', 'bowl', 'bottle'],
        min_duration_s: seconds || 300,
      },
    ];
  }
  return {
    id: uid('r'),
    camera_id: cameraId,
    name,
    prompt_ro: text.trim(),
    zone_tag: zoneTag,
    all_of: allOf,
    action: { type: 'telegram', target: null },
    cooldown_s: 300,
    enabled: true,
  };
}

/** Stand-in for the translator's `explanation_ro`: what the rule watches, in one sentence. */
function mockExplanation(rule: Rule): string {
  const c = rule.all_of[0];
  if (c.kind === 'pose') return 'Vă anunț când un client ridică mâna la o masă.';
  if (c.kind === 'count') {
    return `Vă anunț când la intrare sunt cel puțin ${c.min_count ?? 1} clienți și nu e nimeni de la personal.`;
  }
  if (c.kind === 'objects_unattended') {
    return 'Vă anunț când pe o masă rămân vase și nu se apropie nimeni să le strângă.';
  }
  const min = Math.round((c.min_duration_s ?? 0) / 60);
  return `Vă anunț când la o masă stau clienți de ${min} min și nu a venit nimeni de la personal.`;
}

interface Step {
  at: number;
  run: (api: MockApi) => void;
}

/** One demo loop; repeats every LOOP_MS. Times are milliseconds from loop start. */
const LOOP_MS = 45_000;
const TIMELINE: Step[] = [
  {
    at: 4_000,
    run: (a) =>
      a.emitAlert('r-neservit', 'z-masa-2', 'opened', 'Masa 2: nimeni de la personal de 1 minut'),
  },
  { at: 10_000, run: (a) => a.emitSuggestion() },
  {
    at: 18_000,
    run: (a) => a.emitAlert('r-mana', 'z-masa-1', 'opened', 'Masa 1: un client a ridicat mâna'),
  },
  {
    at: 23_000,
    run: (a) => a.emitAlert('r-mana', 'z-masa-1', 'closed', 'Masa 1: clientul a fost servit'),
  },
  {
    at: 32_000,
    run: (a) => a.emitAlert('r-neservit', 'z-masa-2', 'closed', 'Masa 2: ospătarul a ajuns'),
  },
];

export class MockApi implements ApiClient {
  readonly kind = 'mock';
  private cameras = seedCameras();
  private rules = seedRules();
  private alerts: AlertView[] = seedAlerts();
  private suggestions: StaffSuggestion[] = [];
  private resolved = new Set<string>();
  private alertSubs = new Set<(e: AlertView) => void>();
  private suggestionSubs = new Set<(s: StaffSuggestion) => void>();
  private timers: ReturnType<typeof setTimeout>[] = [];
  private readonly latency: number;

  /** `latencyMs` simulates network delay; `autoplay` starts the demo timeline. */
  constructor(opts: { latencyMs?: number; autoplay?: boolean } = {}) {
    this.latency = opts.latencyMs ?? 250;
    if (opts.autoplay ?? true) this.startLoop();
  }

  private startLoop() {
    for (const step of TIMELINE) this.timers.push(setTimeout(() => step.run(this), step.at));
    this.timers.push(setTimeout(() => this.startLoop(), LOOP_MS));
  }

  dispose() {
    this.timers.forEach(clearTimeout);
    this.timers = [];
  }

  private async delay<T>(value: T): Promise<T> {
    await wait(this.latency);
    return structuredClone(value);
  }

  emitAlert(ruleId: string, zoneId: string, state: AlertEvent['state'], summary: string) {
    const event: AlertEvent = {
      event_id: uid('e'),
      rule_id: ruleId,
      camera_id: 'cam-sala',
      zone_id: zoneId,
      state,
      at: new Date().toISOString(),
      summary_ro: summary,
      snapshot: true,
    };
    this.alerts.push(event);
    this.alertSubs.forEach((cb) => cb(event));
  }

  emitSuggestion() {
    const id = 'sug-track-7';
    if (this.resolved.has(id) || this.suggestions.some((s) => s.suggestion_id === id)) return;
    const s: StaffSuggestion = {
      suggestion_id: id,
      camera_id: 'cam-sala',
      track_id: 7,
      staff_score: 0.82,
      reason_ro: 'Se mișcă între mese, a vizitat 4 mese în 3 minute și stă rar pe loc.',
    };
    this.suggestions.push(s);
    this.suggestionSubs.forEach((cb) => cb(s));
  }

  listCameras() {
    return this.delay(this.cameras);
  }

  listDevices(): Promise<DeviceStatus[]> {
    return this.delay(
      this.cameras.map((c) => ({
        device: c.device,
        state: c.online ? 'online' : 'offline',
        version: '0.1.0',
        cameras: [c.id],
      })),
    );
  }

  async saveZones(cameraId: string, zones: Zone[]): Promise<SavedZones> {
    const cam = this.cameras.find((c) => c.id === cameraId);
    if (!cam) throw new Error(`Camera necunoscută: ${cameraId}`);
    cam.zones = structuredClone(zones);
    return this.delay({ zones, warnings_ro: overlapWarnings(zones) });
  }

  async deleteCamera(id: string) {
    if (!this.cameras.some((c) => c.id === id)) {
      throw new ApiError(`Camera ${id} nu există.`, 'not_found', 404);
    }
    this.cameras = this.cameras.filter((c) => c.id !== id);
    this.rules = this.rules.filter((r) => r.camera_id !== id);
    await this.delay(undefined);
  }

  listRules() {
    return this.delay(this.rules);
  }

  async draftRuleFromText(text: string, cameraId: string): Promise<RuleDraft> {
    if (text.trim().length < 3) throw new ApiError('Cererea este prea scurtă.', 'invalid', 422);
    const cam = this.cameras.find((c) => c.id === cameraId);
    if (!cam) throw new ApiError(`Camera ${cameraId} nu există.`, 'not_found', 404);
    await wait(this.latency * 2);
    const rule = mockRuleFromText(text, cameraId);
    if (!(cam.zones ?? []).some((z) => z.tag === rule.zone_tag)) {
      throw new ApiError(
        `Camera nu are nicio zonă de tip „${rule.zone_tag}”. Desenați-o mai întâi.`,
        'clarify',
        422,
      );
    }
    return this.delay({ rule, explanation_ro: mockExplanation(rule) });
  }

  async createRule(rule: Rule) {
    if (!this.cameras.some((c) => c.id === rule.camera_id)) {
      throw new ApiError(`Camera ${rule.camera_id} nu există.`, 'not_found', 404);
    }
    const saved = structuredClone(rule);
    this.rules = [...this.rules.filter((r) => r.id !== saved.id), saved];
    return this.delay(saved);
  }

  async updateRule(id: string, patch: RulePatch) {
    const rule = this.rules.find((r) => r.id === id);
    if (!rule) throw new ApiError('Regula nu mai există.', 'not_found', 404);
    const saved: Rule = { ...rule, ...structuredClone(patch) };
    this.rules = this.rules.map((r) => (r.id === id ? saved : r));
    return this.delay(saved);
  }

  async deleteRule(id: string) {
    if (!this.rules.some((r) => r.id === id)) {
      throw new ApiError('Regula nu mai există.', 'not_found', 404);
    }
    this.rules = this.rules.filter((r) => r.id !== id);
    await this.delay(undefined);
  }

  async updateCamera(id: string, patch: CameraPatch): Promise<CameraView> {
    const cam = this.cameras.find((c) => c.id === id);
    if (!cam) throw new ApiError(`Camera ${id} nu există.`, 'not_found', 404);
    const saved: CameraView = { ...cam, ...patch };
    this.cameras = this.cameras.map((c) => (c.id === id ? saved : c));
    return this.delay(saved);
  }

  async createCamera(camera: NewCamera): Promise<CameraView> {
    const view: CameraView = { ...camera, zones: [], online: false };
    this.cameras = [...this.cameras.filter((c) => c.id !== camera.id), view];
    return this.delay(view);
  }

  listAlerts() {
    return this.delay(this.alerts);
  }

  subscribeAlerts(cb: (event: AlertView) => void): Unsubscribe {
    this.alertSubs.add(cb);
    return () => this.alertSubs.delete(cb);
  }

  listSuggestions() {
    return this.delay(this.suggestions);
  }

  subscribeSuggestions(cb: (s: StaffSuggestion) => void): Unsubscribe {
    this.suggestionSubs.add(cb);
    return () => this.suggestionSubs.delete(cb);
  }

  subscribeDetections(cameraId: string, cb: (d: Detection[]) => void): Unsubscribe {
    const cam = this.cameras.find((c) => c.id === cameraId);
    if (!cam?.online) return () => undefined;
    const start = Date.now();
    const tick = () => {
      const t = (Date.now() - start) / 1000;
      // Track 7 (staff) walks between the tables; two guests sit at table 2.
      const x = 0.42 + Math.sin(t / 4) * 0.3;
      // Shaped like the edge contract; guest 13 raises a hand now and then.
      const y = 0.22 + Math.cos(t / 3) * 0.04;
      const frame: Detections = {
        camera_id: cameraId,
        ts: new Date().toISOString(),
        tracks: [
          { track_id: 7, role: 'staff', staff_score: 0.86, bbox: [x, y, x + 0.09, y + 0.4] },
          { track_id: 12, role: 'guest', staff_score: 0.1, bbox: [0.44, 0.42, 0.53, 0.72] },
          {
            track_id: 13,
            role: 'guest',
            staff_score: 0.08,
            bbox: [0.64, 0.43, 0.73, 0.72],
            raised_hand: Math.sin(t / 3) > 0.4,
          },
        ],
      };
      cb(fromContract(frame));
    };
    tick();
    const id = setInterval(tick, 400);
    return () => clearInterval(id);
  }

  async confirmSuggestion(id: string) {
    this.resolve(id);
    await this.delay(null);
  }

  async rejectSuggestion(id: string) {
    this.resolve(id);
    await this.delay(null);
  }

  private resolve(id: string) {
    this.resolved.add(id);
    this.suggestions = this.suggestions.filter((s) => s.suggestion_id !== id);
  }

  async uploadStaffPhoto(file: File) {
    if (!file.type.startsWith('image/')) throw new Error('Fișierul trebuie să fie o imagine');
    await this.delay(null);
  }

  getMetrics(): Promise<DashboardMetrics> {
    const online = this.cameras.filter((c) => c.online);
    const today = new Date().toDateString();
    return this.delay({
      devices: online.map((c) => ({
        device: c.device,
        fps: 14 + Math.round(Math.random() * 30) / 10,
        verified_ratio: 0.04 + Math.random() * 0.02,
        cpu_percent: 55 + Math.random() * 15,
      })),
      devices_online: online.length,
      devices_total: this.cameras.length,
      events_today: this.alerts.filter(
        (a) => a.state === 'opened' && new Date(a.at).toDateString() === today,
      ).length,
      alert_latency_ms: 850 + Math.round(Math.random() * 300),
    });
  }

  // --- Accounts, locations, audit, alert lifecycle (see ./mockAccounts.ts) ---

  private location: string | null = null;
  readonly accounts = new MockAccounts(
    () => this.alerts,
    (zoneId) =>
      this.cameras.flatMap((c) => c.zones ?? []).find((z) => z.id === zoneId)?.name ?? zoneId,
    (c: AlertCase) =>
      this.emitAlert(
        c.rule_id,
        c.zone_id,
        'arrived' as AlertEvent['state'],
        `${c.zone_name}: ${c.acknowledged_by ?? 'personalul'} a ajuns`,
      ),
  );

  /** Run a synchronous account call with the simulated latency; errors become rejections. */
  private async call<T>(fn: () => T): Promise<T> {
    await wait(this.latency);
    return fn();
  }

  setLocation(locationId: string | null) {
    this.location = locationId;
  }

  me() {
    return this.call(() => this.accounts.me());
  }

  login(email: string, password: string) {
    return this.call(() => this.accounts.login(email, password));
  }

  register(input: RegisterInput) {
    return this.call(() => this.accounts.register(input));
  }

  logout() {
    return this.call(() => this.accounts.logout());
  }

  getInvite(token: string) {
    return this.call(() => this.accounts.getInvite(token));
  }

  acceptInvite(token: string, input: { name: string; password: string }) {
    return this.call(() => this.accounts.acceptInvite(token, input));
  }

  listLocations() {
    return this.call(() => this.accounts.listLocations());
  }

  createLocation(location: Location) {
    return this.call(() => this.accounts.createLocation(location));
  }

  updateLocation(id: string, patch: Partial<Omit<Location, 'id'>>) {
    return this.call(() => this.accounts.updateLocation(id, patch));
  }

  deleteLocation(id: string) {
    return this.call(() => this.accounts.deleteLocation(id));
  }

  listMembers(locationId: string) {
    return this.call(() => this.accounts.listMembers(locationId));
  }

  updateMember(locationId: string, userId: string, role: Role) {
    return this.call(() => this.accounts.updateMember(locationId, userId, role));
  }

  removeMember(locationId: string, userId: string) {
    return this.call(() => this.accounts.removeMember(locationId, userId));
  }

  createInvite(input: { location_id: string; role: Role; email: string }) {
    return this.call(() => this.accounts.createInvite(input));
  }

  listInvites(locationId: string) {
    return this.call(() => this.accounts.listInvites(locationId));
  }

  revokeInvite(id: string) {
    return this.call(() => this.accounts.revokeInvite(id));
  }

  listAudit(query: AuditQuery) {
    return this.call(() => this.accounts.listAudit(query));
  }

  listAlertCases(query: { location_id: string; state?: string; limit?: number }) {
    return this.call(() => this.accounts.listAlertCases(query));
  }

  ackAlert(eventId: string) {
    return this.call(() => this.accounts.ackAlert(eventId, this.location ?? 'demo'));
  }

  getServiceMetrics(query: { location_id: string; from?: string; to?: string }) {
    return this.call(() => this.accounts.serviceMetrics(query));
  }
}

/** Like the API's `warnings=true`: zones whose bounding boxes overlap (a rough, demo-only check). */
function overlapWarnings(zones: Zone[]): string[] {
  const box = (z: Zone) => {
    const xs = z.polygon.map((p) => p[0]);
    const ys = z.polygon.map((p) => p[1]);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)] as const;
  };
  const out: string[] = [];
  zones.forEach((a, i) =>
    zones.slice(i + 1).forEach((b) => {
      const [ax1, ay1, ax2, ay2] = box(a);
      const [bx1, by1, bx2, by2] = box(b);
      if (ax1 < bx2 && bx1 < ax2 && ay1 < by2 && by1 < ay2) {
        out.push(`„${a.name}” și „${b.name}” se suprapun; o persoană poate fi numărată la ambele.`);
      }
    }),
  );
  return out;
}
