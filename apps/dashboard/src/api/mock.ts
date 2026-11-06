// In-browser stand-in for the backend: realistic demo data plus a scripted timeline in which
// alerts open and close, and a "looks like staff" suggestion appears. Used when VITE_API_URL
// is unset, so the dashboard can be built and demoed before the API exists.
import type {
  AlertEvent,
  Condition,
  DeviceStatus,
  Rule,
  StaffSuggestion,
  Zone,
} from '../contracts';
import type { ApiClient, CameraView, DashboardMetrics, Detection, Unsubscribe } from './client';

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
        { id: 'z-masa-1', name: 'Masa 1', tag: 'table', polygon: [[0.08, 0.52], [0.34, 0.5], [0.36, 0.82], [0.06, 0.84]] },
        { id: 'z-masa-2', name: 'Masa 2', tag: 'table', polygon: [[0.44, 0.5], [0.7, 0.5], [0.72, 0.82], [0.42, 0.82]] },
        { id: 'z-intrare', name: 'Intrare', tag: 'entrance', polygon: [[0.78, 0.18], [0.96, 0.18], [0.96, 0.62], [0.78, 0.62]] },
      ],
    },
    {
      id: 'cam-terasa',
      name: 'Terasă',
      source: 'rtsp://192.168.1.21:554/stream1',
      device: 'edge-terasa',
      online: false,
      zones: [
        { id: 'z-masa-3', name: 'Masa 3', tag: 'table', polygon: [[0.2, 0.4], [0.5, 0.4], [0.5, 0.75], [0.2, 0.75]] },
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
  ];
}

function seedAlerts(): AlertEvent[] {
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

interface Step {
  at: number;
  run: (api: MockApi) => void;
}

/** One demo loop; repeats every LOOP_MS. Times are milliseconds from loop start. */
const LOOP_MS = 45_000;
const TIMELINE: Step[] = [
  { at: 4_000, run: (a) => a.emitAlert('r-neservit', 'z-masa-2', 'opened', 'Masa 2: nimeni de la personal de 1 minut') },
  { at: 10_000, run: (a) => a.emitSuggestion() },
  { at: 18_000, run: (a) => a.emitAlert('r-mana', 'z-masa-1', 'opened', 'Masa 1: un client a ridicat mâna') },
  { at: 23_000, run: (a) => a.emitAlert('r-mana', 'z-masa-1', 'closed', 'Masa 1: clientul a fost servit') },
  { at: 32_000, run: (a) => a.emitAlert('r-neservit', 'z-masa-2', 'closed', 'Masa 2: ospătarul a ajuns') },
];

export class MockApi implements ApiClient {
  readonly kind = 'mock';
  private cameras = seedCameras();
  private rules = seedRules();
  private alerts = seedAlerts();
  private suggestions: StaffSuggestion[] = [];
  private resolved = new Set<string>();
  private alertSubs = new Set<(e: AlertEvent) => void>();
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

  async saveZones(cameraId: string, zones: Zone[]) {
    const cam = this.cameras.find((c) => c.id === cameraId);
    if (!cam) throw new Error(`Camera necunoscută: ${cameraId}`);
    cam.zones = structuredClone(zones);
    return this.delay(zones);
  }

  listRules() {
    return this.delay(this.rules);
  }

  async createRuleFromText(text: string, cameraId: string) {
    if (text.trim() === '') throw new Error('Cererea este goală');
    await wait(this.latency * 2);
    const rule = mockRuleFromText(text, cameraId);
    this.rules.push(rule);
    return this.delay(rule);
  }

  listAlerts() {
    return this.delay(this.alerts);
  }

  subscribeAlerts(cb: (event: AlertEvent) => void): Unsubscribe {
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
      cb([
        { track_id: 7, role: 'staff', box: [x, 0.22 + Math.cos(t / 3) * 0.04, 0.09, 0.4] },
        { track_id: 12, role: 'guest', box: [0.47, 0.42, 0.09, 0.3] },
        { track_id: 13, role: 'guest', box: [0.6, 0.43, 0.09, 0.29] },
      ]);
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
}
