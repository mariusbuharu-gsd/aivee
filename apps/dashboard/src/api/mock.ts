// In-browser stand-in for the backend: realistic demo data plus a scripted timeline in which
// alerts open and close, and a "looks like staff" suggestion appears. Used when VITE_API_URL
// is unset, so the dashboard can be built and demoed before the API exists.
import type { AlertEvent, Condition, Detections, Rule, Zone } from '../contracts';
import { MockAccounts } from './mockAccounts';
import {
  ApiError,
  MAX_VIDEO_BYTES,
  VIDEO_TYPES,
  type AlertView,
  type ApiClient,
  type CameraFrame,
  type CameraView,
  type DeviceView,
  type SuggestionView,
  type DashboardMetrics,
  type Detection,
  type AlertCase,
  type AuditQuery,
  type Location,
  type CameraPatch,
  type NewCamera,
  type SavedZones,
  type StaffProfile,
  type RulePatch,
  type RegisterInput,
  type Role,
  type RuleDraft,
  type RuleStats,
  type Unsubscribe,
  type NewVideoUpload,
  type VideoAlert,
  type VideoUpload,
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

/** Alerts of the seeded rules on the 6 days before today, oldest first (today comes from the feed). */
const RULE_HISTORY: Record<string, number[]> = {
  'r-neservit': [3, 5, 2, 4, 6, 3],
  'r-mana': [1, 2, 0, 3, 1, 2],
  'r-pahar': [0, 0, 1, 0, 0, 1],
};

/** Cameras of the locations the mock does not serve cameras for (only `demo` has real ones). */
const OTHER_CAMERAS: Record<string, { total: number; online: number }> = {
  centru: { total: 2, online: 1 },
};

const utcDay = (iso: string | Date) => new Date(iso).toISOString().slice(0, 10);

/**
 * Stand-in for the edge's face-blurred person crop: a silhouette in the waiter's dark-red
 * shirt, the head a plain blurred disc. Nothing in it could be a real face.
 */
function personSketch(): string {
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 80">' +
    '<defs><filter id="b"><feGaussianBlur stdDeviation="3"/></filter></defs>' +
    '<rect width="60" height="80" fill="#1b1d22"/>' +
    '<path d="M8 80 C10 52 18 44 30 44 C42 44 50 52 52 80 Z" fill="#7a1f2b"/>' +
    '<circle cx="30" cy="27" r="12" fill="#a3a9b4" filter="url(#b)"/>' +
    '</svg>';
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

/**
 * Stand-in camera still for the mock (the real one is the camera's latest face-blurred JPEG):
 * the room in 16:9, each table drawn where its zone is, so zones line up when drawn over it.
 */
export function roomSketch(zones: Zone[]): string {
  const W = 320;
  const H = 180;
  const shapes = zones.map((z) => {
    const xs = z.polygon.map((p) => p[0] * W);
    const ys = z.polygon.map((p) => p[1] * H);
    const [x, y] = [Math.min(...xs), Math.min(...ys)];
    const [w, h] = [Math.max(...xs) - x, Math.max(...ys) - y];
    const r = (v: number) => v.toFixed(1);
    if (z.tag === 'entrance') {
      return `<rect x="${r(x + w * 0.2)}" y="${r(y)}" width="${r(w * 0.6)}" height="${r(h)}" fill="#2b2f37" stroke="#4a505c" stroke-width="2"/>`;
    }
    const cx = x + w / 2;
    const cy = y + h / 2;
    return (
      `<ellipse cx="${r(cx)}" cy="${r(cy)}" rx="${r(w * 0.36)}" ry="${r(h * 0.3)}" fill="#2a2d34" stroke="#8a909c" stroke-width="1.5"/>` +
      `<circle cx="${r(cx - w * 0.45)}" cy="${r(cy)}" r="${r(h * 0.12)}" fill="#33363e"/>` +
      `<circle cx="${r(cx + w * 0.45)}" cy="${r(cy)}" r="${r(h * 0.12)}" fill="#33363e"/>`
    );
  });
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}">` +
    `<rect width="${W}" height="${H}" fill="#1b1d22"/>` +
    `<path d="M0 ${H * 0.36} L${W} ${H * 0.3}" stroke="#262930" stroke-width="2"/>` +
    shapes.join('') +
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

const DEMO_VIDEO = 'a1b2c3d4';

/** One analysed clip so the "Analiză video" page has something to show without an API. */
function seedVideos(): { upload: VideoUpload; alerts: VideoAlert[] }[] {
  const alert = (
    n: number,
    zone: [string, string],
    summary: string,
    at: number,
    arrived: number | null,
    closed: number,
    reason: string | null = null,
  ): VideoAlert => ({
    event_id: `${DEMO_VIDEO}-e${n}`,
    zone_id: zone[0],
    zone_name: zone[1],
    summary_ro: summary,
    state: 'closed',
    at_s: at,
    arrived_at_s: arrived,
    closed_at_s: closed,
    wait_s: (arrived ?? closed) - at,
    closed_reason: reason,
    snapshot_url: null,
  });
  const masa1: [string, string] = ['z-masa-1', 'Masa 1'];
  const masa2: [string, string] = ['z-masa-2', 'Masa 2'];
  const alerts = [
    alert(1, masa2, 'Masa 2: neservită de 1 min', 12, 41, 43),
    alert(2, ['z-intrare', 'Intrare'], 'Intrare: 3 clienți așteaptă', 38, null, 50),
    alert(3, masa1, 'Masa 1: un client a ridicat mâna', 61, 70, 72),
    alert(4, masa1, 'Masa 1: neservită de 1 min', 80, null, 95, 'video_end'),
  ];
  return [
    {
      upload: {
        id: DEMO_VIDEO,
        location_id: 'demo',
        camera_id: `video-${DEMO_VIDEO}`,
        source_camera_id: 'cam-sala',
        filename: 'sala-1.mp4',
        size_bytes: 48_234_496,
        rotate: 0,
        status: 'done',
        progress: 1,
        duration_s: 95,
        events: alerts.length,
        error_ro: null,
        created_at: minutesAgo(90),
        started_at: minutesAgo(90),
        finished_at: minutesAgo(88),
        created_by: { id: 'u-manager', name: 'Mihai Ionescu' },
      },
      alerts,
    },
  ];
}

/** A new mock upload waits this long, then "analyses" for VIDEO_RUN_MS. */
const VIDEO_QUEUE_MS = 1_500;
const VIDEO_RUN_MS = 6_000;

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
  private suggestions: SuggestionView[] = [];
  private videos = seedVideos();
  private staffProfiles: StaffProfile[] = [];
  private resolved = new Set<string>();
  private alertSubs = new Set<(e: AlertView) => void>();
  private suggestionSubs = new Set<(s: SuggestionView) => void>();
  private timers: ReturnType<typeof setTimeout>[] = [];
  private readonly latency: number;
  /** When each offline device went away (as the API's `last_seen`): 14 min before startup. */
  private readonly offlineSince = minutesAgo(14);

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
    const event: AlertView = {
      event_id: uid('e'),
      rule_id: ruleId,
      camera_id: 'cam-sala',
      zone_id: zoneId,
      state,
      at: new Date().toISOString(),
      summary_ro: summary,
      snapshot: true,
      // A stand-in snapshot on open, so the Alerte cards show one as with the real API.
      ...(state === 'opened' ? { snapshot_url: tableSketch(true) } : {}),
    };
    this.alerts.push(event);
    this.alertSubs.forEach((cb) => cb(event));
  }

  emitSuggestion() {
    const id = 'sug-track-7';
    if (this.resolved.has(id) || this.suggestions.some((s) => s.suggestion_id === id)) return;
    const s: SuggestionView = {
      suggestion_id: id,
      camera_id: 'cam-sala',
      track_id: 7,
      staff_score: 0.82,
      reason_ro: 'Se mișcă între mese, a vizitat 4 mese în 3 minute și stă rar pe loc.',
      snapshot: true,
      snapshot_url: personSketch(),
    };
    this.suggestions.push(s);
    this.suggestionSubs.forEach((cb) => cb(s));
  }

  listCameras() {
    return this.delay(this.cameras);
  }

  listDevices(): Promise<DeviceView[]> {
    return this.delay(
      this.cameras.map((c) => ({
        device: c.device,
        state: c.online ? 'online' : 'offline',
        version: '0.1.0',
        cameras: [c.id],
        site: 'demo',
        // Online edges send metrics every ~5 s, so the last one is a couple of seconds old.
        last_seen: c.online ? new Date(Date.now() - 2_000).toISOString() : this.offlineSince,
      })),
    );
  }

  async captureFrame(cameraId: string): Promise<CameraFrame> {
    await wait(this.latency);
    const cam = this.cameras.find((c) => c.id === cameraId);
    if (!cam) throw new ApiError('Camera nu există.', 'not_found', 404);
    return {
      url: roomSketch(cam.zones ?? []),
      at: cam.online ? new Date(Date.now() - 20_000).toISOString() : this.offlineSince,
      release: () => undefined,
    };
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

  getRuleStats(days = 7): Promise<RuleStats> {
    const dates = Array.from({ length: days }, (_, i) =>
      utcDay(new Date(Date.now() - (days - 1 - i) * 86_400_000)),
    );
    const today = dates[dates.length - 1];
    return this.delay({
      days: dates,
      rules: this.rules.map((r) => {
        const history = RULE_HISTORY[r.id] ?? [];
        const now = this.alerts.filter(
          (a) => a.rule_id === r.id && a.state === 'opened' && utcDay(a.at) === today,
        ).length;
        const per_day = dates.map((_, i) =>
          i === days - 1 ? now : (history[history.length - (days - 1 - i)] ?? 0),
        );
        return { rule_id: r.id, total: per_day.reduce((a, b) => a + b, 0), per_day };
      }),
    });
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

  subscribeSuggestions(cb: (s: SuggestionView) => void): Unsubscribe {
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
    const profile = this.staffProfiles[0];
    if (profile) profile.examples += 1;
    else
      this.staffProfiles.push({
        id: 'uniforma',
        name: 'Uniformă',
        description_ro: '',
        examples: 1,
        has_centroid: true,
      });
    await this.delay(null);
  }

  /** Empty until a photo is uploaded, so the setup checklist shows "Poze cu uniforma" to do. */
  listStaffProfiles() {
    return this.delay(this.staffProfiles);
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

  // --- Video analysis: a new upload moves queued → running → done with the clock ---

  async uploadVideo({ file, rotate = 0, copy_from_camera_id }: NewVideoUpload) {
    if (!VIDEO_TYPES.includes(file.type)) {
      throw new ApiError('Fișierul trebuie să fie un video MP4, MOV sau WebM.', 'invalid', 422);
    }
    if (file.size > MAX_VIDEO_BYTES) {
      throw new ApiError('Clipul are mai mult de 200 MB.', 'too_large', 422);
    }
    const source = copy_from_camera_id ?? this.cameras[0]?.id ?? null;
    if (source && !this.cameras.some((c) => c.id === source)) {
      throw new ApiError(`Camera ${source} nu există.`, 'not_found', 404);
    }
    const id = Math.random().toString(16).slice(2, 10).padEnd(8, '0');
    const demo = this.videos.find((v) => v.upload.id === DEMO_VIDEO)?.alerts ?? [];
    const upload: VideoUpload = {
      id,
      location_id: this.location ?? 'demo',
      camera_id: `video-${id}`,
      source_camera_id: source,
      filename: file.name,
      size_bytes: file.size,
      rotate,
      status: 'queued',
      progress: 0,
      duration_s: null,
      events: 0,
      error_ro: null,
      created_at: new Date().toISOString(),
      started_at: null,
      finished_at: null,
      created_by: null,
    };
    const alerts = demo
      .slice(0, 2)
      .map((a, i) => ({ ...a, event_id: `${id}-e${i + 1}`, closed_reason: null }));
    this.videos.unshift({ upload, alerts });
    return this.delay(upload);
  }

  /** The upload as it would be now, given how long ago it was created. */
  private videoNow(id: string): { upload: VideoUpload; alerts: VideoAlert[] } {
    const v = this.videos.find((x) => x.upload.id === id);
    if (!v) throw new ApiError('Clipul nu există.', 'not_found', 404);
    const u = v.upload;
    if (u.status === 'done' || u.status === 'failed') return v;
    const elapsed = Date.now() - Date.parse(u.created_at) - VIDEO_QUEUE_MS;
    if (elapsed < 0) return v;
    const start = new Date(Date.parse(u.created_at) + VIDEO_QUEUE_MS).toISOString();
    if (elapsed < VIDEO_RUN_MS) {
      const progress = elapsed / VIDEO_RUN_MS;
      const found = v.alerts.filter((a) => a.at_s / 60 <= progress).length;
      return {
        ...v,
        upload: { ...u, status: 'running', started_at: start, progress, events: found },
      };
    }
    v.upload = {
      ...u,
      status: 'done',
      progress: 1,
      duration_s: 60,
      events: v.alerts.length,
      started_at: start,
      finished_at: new Date().toISOString(),
    };
    return v;
  }

  async listVideos() {
    const here = this.location ?? 'demo';
    const all = this.videos.map((v) => this.videoNow(v.upload.id).upload);
    return this.delay(all.filter((u) => u.location_id === here));
  }

  async getVideo(id: string) {
    return this.delay(this.videoNow(id).upload);
  }

  async videoEvents(id: string) {
    const { upload, alerts } = this.videoNow(id);
    return this.delay(alerts.slice(0, upload.events));
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
    return this.call(() =>
      this.accounts.listLocations().map((l) => {
        const counts =
          l.id === 'demo'
            ? {
                total: this.cameras.length,
                online: this.cameras.filter((c) => c.online).length,
              }
            : (OTHER_CAMERAS[l.id] ?? { total: 0, online: 0 });
        return { ...l, cameras_total: counts.total, cameras_online: counts.online };
      }),
    );
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

  createTelegramLink(locationId: string) {
    return this.call(() => this.accounts.createTelegramLink(locationId));
  }

  getTelegramStatus(locationId: string) {
    return this.call(() => this.accounts.getTelegramStatus(locationId));
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

  getServiceHeatmap(query: { location_id: string; from?: string; to?: string }) {
    return this.call(() => this.accounts.serviceHeatmap(query));
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
