// Thin client for the FastAPI service (apps/api). Shapes follow its routers and schemas;
// adjust here only, the rest of the dashboard depends on ApiClient.
import type { DeviceStatus, Rule, StaffSuggestion, Zone } from '../contracts';
import {
  ApiError,
  type AlertView,
  type ApiClient,
  type CameraView,
  type DashboardMetrics,
  type Detection,
  type NewCamera,
  type RuleDraft,
  type Unsubscribe,
} from './client';

type WsMessage =
  | { type: 'alert'; data: AlertView }
  | { type: 'suggestion'; data: StaffSuggestion }
  | { type: 'detections'; camera_id: string; data: Detection[] };

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
      res = await fetch(`${this.base}${path}`, {
        ...init,
        headers:
          init?.body instanceof FormData
            ? init.headers
            : { 'Content-Type': 'application/json', ...init?.headers },
      });
    } catch {
      throw new ApiError('Serverul nu răspunde. Verificați conexiunea.', 'network');
    }
    if (!res.ok) throw await toApiError(res);
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  /** Snapshot paths are relative to the API (`/api/snapshots/<id>`). */
  private withSnapshot = (e: AlertView): AlertView => ({
    ...e,
    snapshot_url: e.snapshot_url ? new URL(e.snapshot_url, `${this.base}/`).toString() : null,
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

  listDevices() {
    return this.request<DeviceStatus[]>('/api/devices');
  }

  saveZones(cameraId: string, zones: Zone[]) {
    return this.request<Zone[]>(`/api/cameras/${encodeURIComponent(cameraId)}/zones`, {
      method: 'PUT',
      body: JSON.stringify(zones),
    });
  }

  listRules() {
    return this.request<Rule[]>('/api/rules');
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

  async listAlerts() {
    return (await this.request<AlertView[]>('/api/events')).map(this.withSnapshot);
  }

  listSuggestions() {
    return this.request<StaffSuggestion[]>('/api/staff/suggestions');
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

  getMetrics() {
    return this.request<DashboardMetrics>('/api/metrics');
  }

  subscribeAlerts(cb: (event: AlertView) => void): Unsubscribe {
    return this.listen((m) => m.type === 'alert' && cb(this.withSnapshot(m.data)));
  }

  subscribeSuggestions(cb: (s: StaffSuggestion) => void): Unsubscribe {
    return this.listen((m) => m.type === 'suggestion' && cb(m.data));
  }

  /** The API may never send `detections`; then the overlay simply stays empty. */
  subscribeDetections(cameraId: string, cb: (d: Detection[]) => void): Unsubscribe {
    return this.listen(
      (m) =>
        m.type === 'detections' && m.camera_id === cameraId && Array.isArray(m.data) && cb(m.data),
    );
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
      ws.onclose = () => {
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
}
