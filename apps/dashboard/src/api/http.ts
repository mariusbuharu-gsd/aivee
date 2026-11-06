// Thin client for the FastAPI service (apps/api). Shapes follow its routers and schemas;
// adjust here only, the rest of the dashboard depends on ApiClient.
import type { Rule, Zone } from '../contracts';
import {
  ApiError,
  UNAUTHORIZED_EVENT,
  type AlertCase,
  type AlertView,
  type AuditPage,
  type AlertPageQuery,
  type AuditQuery,
  type Invite,
  type InviteInfo,
  type Location,
  type TelegramLink,
  type TelegramStatus,
  type Me,
  type Member,
  type RegisterInput,
  type Role,
  type ServiceHeatmap,
  type ServiceMetrics,
  type ApiClient,
  type CameraFrame,
  type CameraView,
  type DeviceView,
  type DashboardMetrics,
  type Detection,
  type CameraPatch,
  type NewCamera,
  type PendingInvite,
  type SavedZones,
  type StaffProfile,
  type SuggestionView,
  type RulePatch,
  type RuleDraft,
  type RuleStats,
  type Unsubscribe,
  type NewVideoUpload,
  type VideoAlert,
  type VideoUpload,
} from './client';
import { parseDetections } from '../live/detections';

type WsMessage =
  | { type: 'alert'; data: AlertView }
  | { type: 'suggestion'; data: SuggestionView }
  | { type: 'detections'; camera_id: string; data: unknown };

/** `POST /api/rules/from-text` response. */
interface FromTextOut {
  rule: Rule;
  explanation_ro: string;
  saved: boolean;
}

const FALLBACK_MESSAGE: Record<number, string> = {
  404: 'Resursa nu există.',
  409: 'Există deja.',
  422: 'Datele trimise nu sunt valide.',
  429: 'Prea multe cereri. Încercați din nou peste câteva secunde.',
  503: 'Serviciul nu este disponibil acum.',
};

/**
 * Turn an error response into an ApiError. Domain errors come as
 * `{detail: {code, message_ro}}`; FastAPI validation errors as `{detail: [...]}`.
 */
export async function toApiError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* not JSON */
  }
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const d = detail as { code?: unknown; message_ro?: unknown };
    if (typeof d.message_ro === 'string') {
      return new ApiError(d.message_ro, typeof d.code === 'string' ? d.code : 'error', res.status);
    }
  }
  // FastAPI's own validation errors: {detail: [{loc, msg, type}, ...]}.
  if (Array.isArray(detail) && res.status === 422) {
    const fields = detail
      .map((d) => (d as { loc?: unknown }).loc)
      .map((loc) => (Array.isArray(loc) ? loc[loc.length - 1] : null))
      .filter((f): f is string => typeof f === 'string');
    const message = fields.length
      ? `Date invalide: verificați ${[...new Set(fields)].join(', ')}.`
      : 'Date invalide. Verificați câmpurile.';
    return new ApiError(message, 'invalid', res.status);
  }
  const code = res.status === 422 ? 'invalid' : 'error';
  const message = FALLBACK_MESSAGE[res.status] ?? `Eroare de server (${res.status}).`;
  return new ApiError(message, code, res.status);
}

export class HttpApi implements ApiClient {
  readonly kind = 'http';
  private readonly base: string;

  constructor(baseUrl: string) {
    this.base = baseUrl.replace(/\/$/, '');
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    let res: Response;
    try {
      res = await fetch(`${this.base}${this.scoped(path)}`, {
        ...init,
        credentials: 'include',
        headers:
          init?.body instanceof FormData
            ? init.headers
            : { 'Content-Type': 'application/json', ...init?.headers },
      });
    } catch {
      throw new ApiError('Serverul nu răspunde. Verificați conexiunea.', 'network');
    }
    if (res.status === 401 && !path.startsWith('/api/auth/')) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    if (!res.ok) throw await toApiError(res);
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  /** Snapshot paths are relative to the API (`/api/snapshots/<id>`). */
  private absolute = (path: string | null | undefined): string | null =>
    path ? new URL(path, `${this.base}/`).toString() : null;

  private withSnapshot = (e: AlertView): AlertView => ({
    ...e,
    snapshot_url: this.absolute(e.snapshot_url),
    before_snapshot_url: this.absolute(e.before_snapshot_url),
  });

  private withPhoto = (s: SuggestionView): SuggestionView => ({
    ...s,
    snapshot_url: this.absolute(s.snapshot_url),
  });

  listCameras() {
    return this.request<CameraView[]>('/api/cameras');
  }

  createCamera(camera: NewCamera) {
    // `device` is sent for forward compatibility; the API currently assigns its own DEVICE.
    return this.request<CameraView>('/api/cameras', {
      method: 'POST',
      body: JSON.stringify(camera),
    });
  }

  updateCamera(id: string, patch: CameraPatch) {
    return this.request<CameraView>(`/api/cameras/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
  }

  async deleteCamera(id: string) {
    await this.request<undefined>(`/api/cameras/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }

  listDevices() {
    return this.request<DeviceView[]>('/api/devices');
  }

  /** Fetched (not a bare `<img src>`) to read `X-Frame-At` and to fail into a placeholder. */
  /** A bare `<img src>`: the session cookie goes along, as with snapshot images. */
  liveMjpegUrl(cameraId: string): string {
    return `${this.base}${this.scoped(`/api/cameras/${encodeURIComponent(cameraId)}/live.mjpg`)}`;
  }

  async captureFrame(cameraId: string): Promise<CameraFrame> {
    const path = this.scoped(`/api/cameras/${encodeURIComponent(cameraId)}/frame`);
    let res: Response;
    try {
      res = await fetch(`${this.base}${path}`, { credentials: 'include', cache: 'no-store' });
    } catch {
      throw new ApiError('Serverul nu răspunde. Verificați conexiunea.', 'network');
    }
    if (res.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    if (!res.ok) throw await toApiError(res);
    const url = URL.createObjectURL(await res.blob());
    return {
      url,
      at: res.headers.get('X-Frame-At'),
      release: () => URL.revokeObjectURL(url),
    };
  }

  saveZones(cameraId: string, zones: Zone[]) {
    return this.request<SavedZones>(
      `/api/cameras/${encodeURIComponent(cameraId)}/zones?warnings=true`,
      {
        method: 'PUT',
        body: JSON.stringify(zones),
      },
    );
  }

  listRules() {
    return this.request<Rule[]>('/api/rules');
  }

  getRuleStats(days = 7) {
    return this.request<RuleStats>(`/api/rules/stats?days=${days}`);
  }

  async draftRuleFromText(text: string, cameraId: string): Promise<RuleDraft> {
    const out = await this.request<FromTextOut>('/api/rules/from-text', {
      method: 'POST',
      body: JSON.stringify({ text, camera_id: cameraId, save: false }),
    });
    return { rule: out.rule, explanation_ro: out.explanation_ro };
  }

  createRule(rule: Rule) {
    return this.request<Rule>('/api/rules', { method: 'POST', body: JSON.stringify(rule) });
  }

  updateRule(id: string, patch: RulePatch) {
    return this.request<Rule>(`/api/rules/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
  }

  async deleteRule(id: string) {
    await this.request<undefined>(`/api/rules/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }

  async listAlerts(q: AlertPageQuery = {}) {
    const qs = query(q);
    return (await this.request<AlertView[]>(`/api/events${qs ? `?${qs}` : ''}`)).map(
      this.withSnapshot,
    );
  }

  async listSuggestions() {
    return (await this.request<SuggestionView[]>('/api/staff/suggestions')).map(this.withPhoto);
  }

  async confirmSuggestion(id: string) {
    await this.request<unknown>(`/api/staff/suggestions/${encodeURIComponent(id)}/confirm`, {
      method: 'POST',
    });
  }

  async rejectSuggestion(id: string) {
    await this.request<unknown>(`/api/staff/suggestions/${encodeURIComponent(id)}/reject`, {
      method: 'POST',
    });
  }

  async uploadStaffPhoto(file: File) {
    const body = new FormData();
    body.append('photo', file);
    await this.request<unknown>('/api/staff/photos', { method: 'POST', body });
  }

  listStaffProfiles() {
    return this.request<StaffProfile[]>('/api/staff/profiles');
  }

  getMetrics() {
    return this.request<DashboardMetrics>('/api/metrics');
  }

  uploadVideo({ file, rotate, copy_from_camera_id }: NewVideoUpload) {
    const body = new FormData();
    body.append('file', file);
    if (this.location) body.append('location_id', this.location);
    if (rotate !== undefined) body.append('rotate', String(rotate));
    if (copy_from_camera_id) body.append('copy_from_camera_id', copy_from_camera_id);
    return this.request<VideoUpload>('/api/videos', { method: 'POST', body });
  }

  listVideos() {
    return this.request<VideoUpload[]>('/api/videos');
  }

  getVideo(id: string) {
    return this.request<VideoUpload>(`/api/videos/${encodeURIComponent(id)}`);
  }

  async videoEvents(id: string) {
    const alerts = await this.request<VideoAlert[]>(`/api/videos/${encodeURIComponent(id)}/events`);
    return alerts.map((a) => ({ ...a, snapshot_url: this.absolute(a.snapshot_url) }));
  }

  subscribeAlerts(cb: (event: AlertView) => void): Unsubscribe {
    return this.listen((m) => m.type === 'alert' && cb(this.withSnapshot(m.data)));
  }

  subscribeSuggestions(cb: (s: SuggestionView) => void): Unsubscribe {
    return this.listen((m) => m.type === 'suggestion' && cb(this.withPhoto(m.data)));
  }

  /** Live boxes for one camera; malformed frames are ignored (see `parseDetections`). */
  subscribeDetections(cameraId: string, cb: (d: Detection[]) => void): Unsubscribe {
    return this.listen((m) => {
      if (m.type !== 'detections' || m.camera_id !== cameraId) return;
      const detections = parseDetections(m.data);
      if (detections) cb(detections);
    });
  }

  /** One socket per subscriber, reconnecting with a fixed back-off. Good enough for a demo. */
  private listen(onMessage: (m: WsMessage) => void): Unsubscribe {
    const url = `${this.base.replace(/^http/, 'ws')}/ws/events`;
    let ws: WebSocket | null = null;
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const connect = () => {
      ws = new WebSocket(url);
      ws.onmessage = (e: MessageEvent<string>) => {
        try {
          const m = JSON.parse(e.data) as WsMessage | null;
          if (m && typeof m === 'object' && 'type' in m) onMessage(m);
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = (e: CloseEvent) => {
        // 1008 = policy violation: the API closes the socket when there is no session.
        if (e.code === 1008) {
          stopped = true;
          window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
          return;
        }
        if (!stopped) retry = setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      ws?.close();
    };
  }

  // --- Accounts, locations, audit, alert lifecycle (docs/plans/2026-11-06-auth-roles-audit.md) ---

  private location: string | null = null;

  setLocation(locationId: string | null) {
    this.location = locationId;
  }

  /** Location-scoped endpoints get `location_id` unless the caller passed one. */
  private scoped(path: string): string {
    const global = /^\/api\/(auth|invites|locations)(\/|$|\?)/.test(path);
    if (!this.location || global || /[?&]location_id=/.test(path)) return path;
    return `${path}${path.includes('?') ? '&' : '?'}location_id=${encodeURIComponent(this.location)}`;
  }

  private post<T>(path: string, body?: unknown) {
    return this.request<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  me() {
    return this.request<Me>('/api/auth/me');
  }

  login(email: string, password: string) {
    return this.post<Me>('/api/auth/login', { email, password });
  }

  register(input: RegisterInput) {
    return this.post<Me>('/api/auth/register', input);
  }

  async logout() {
    await this.post<unknown>('/api/auth/logout');
  }

  getInvite(token: string) {
    return this.request<InviteInfo>(`/api/invites/${encodeURIComponent(token)}`);
  }

  acceptInvite(token: string, input: { name: string; password: string }) {
    return this.post<Me>(`/api/invites/${encodeURIComponent(token)}/accept`, input);
  }

  listLocations() {
    return this.request<Location[]>('/api/locations');
  }

  createLocation(location: Location) {
    return this.post<Location>('/api/locations', location);
  }

  updateLocation(id: string, patch: Partial<Omit<Location, 'id'>>) {
    return this.request<Location>(`/api/locations/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
  }

  async deleteLocation(id: string) {
    await this.request<unknown>(`/api/locations/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }

  createTelegramLink(locationId: string) {
    return this.post<TelegramLink>(
      `/api/locations/${encodeURIComponent(locationId)}/telegram/link`,
      {},
    );
  }

  getTelegramStatus(locationId: string) {
    return this.request<TelegramStatus>(
      `/api/locations/${encodeURIComponent(locationId)}/telegram`,
    );
  }

  listMembers(locationId: string) {
    return this.request<Member[]>(`/api/locations/${encodeURIComponent(locationId)}/members`);
  }

  updateMember(locationId: string, userId: string, role: Role) {
    return this.request<Member>(
      `/api/locations/${encodeURIComponent(locationId)}/members/${encodeURIComponent(userId)}`,
      { method: 'PATCH', body: JSON.stringify({ role }) },
    );
  }

  async removeMember(locationId: string, userId: string) {
    await this.request<unknown>(
      `/api/locations/${encodeURIComponent(locationId)}/members/${encodeURIComponent(userId)}`,
      { method: 'DELETE' },
    );
  }

  createInvite(input: { location_id: string; role: Role; email: string }) {
    return this.post<Invite>('/api/invites', input);
  }

  listInvites(locationId: string) {
    return this.request<PendingInvite[]>(
      `/api/invites?location_id=${encodeURIComponent(locationId)}`,
    );
  }

  async revokeInvite(id: string) {
    await this.request<undefined>(`/api/invites/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }

  listAudit(q: AuditQuery) {
    return this.request<AuditPage>(`/api/audit?${query(q)}`);
  }

  listAlertCases(q: { location_id: string; state?: string; limit?: number; before?: string }) {
    return this.request<AlertCase[]>(`/api/alerts?${query(q)}`);
  }

  ackAlert(eventId: string) {
    return this.post<AlertCase>(`/api/alerts/${encodeURIComponent(eventId)}/ack`);
  }

  getServiceMetrics(q: { location_id: string; from?: string; to?: string }) {
    return this.request<ServiceMetrics>(`/api/metrics/service?${query(q)}`);
  }

  getServiceHeatmap(q: { location_id: string; from?: string; to?: string }) {
    return this.request<ServiceHeatmap>(`/api/metrics/service/heatmap?${query(q)}`);
  }
}

/** Query string from the defined, non-empty values. */
function query(params: object): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v));
  }
  return q.toString();
}
