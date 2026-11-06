// Thin client for the FastAPI service. Endpoint shapes follow the implementation plan;
// adjust here only, the rest of the dashboard depends on ApiClient.
import type {
  AlertEvent,
  DeviceStatus,
  Rule,
  StaffSuggestion,
  Zone,
} from '../contracts';
import type { ApiClient, CameraView, DashboardMetrics, Detection, Unsubscribe } from './client';

type WsMessage =
  | { type: 'alert'; data: AlertEvent }
  | { type: 'suggestion'; data: StaffSuggestion }
  | { type: 'detections'; camera_id: string; data: Detection[] };

export class HttpApi implements ApiClient {
  readonly kind = 'http';
  private readonly base: string;

  constructor(baseUrl: string) {
    this.base = baseUrl.replace(/\/$/, '');
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      ...init,
      headers:
        init?.body instanceof FormData
          ? init.headers
          : { 'Content-Type': 'application/json', ...init?.headers },
    });
    if (!res.ok) throw new Error(`${init?.method ?? 'GET'} ${path} → ${res.status}`);
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  listCameras() {
    return this.request<CameraView[]>('/api/cameras');
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

  createRuleFromText(text: string, cameraId: string) {
    return this.request<Rule>('/api/rules/from-text', {
      method: 'POST',
      body: JSON.stringify({ text, camera_id: cameraId }),
    });
  }

  listAlerts() {
    return this.request<AlertEvent[]>('/api/events');
  }

  listSuggestions() {
    return this.request<StaffSuggestion[]>('/api/staff/suggestions');
  }

  async confirmSuggestion(id: string) {
    await this.request<void>(`/api/staff/suggestions/${encodeURIComponent(id)}/confirm`, {
      method: 'POST',
    });
  }

  async rejectSuggestion(id: string) {
    await this.request<void>(`/api/staff/suggestions/${encodeURIComponent(id)}/reject`, {
      method: 'POST',
    });
  }

  async uploadStaffPhoto(file: File) {
    const body = new FormData();
    body.append('photo', file);
    await this.request<void>('/api/staff/photos', { method: 'POST', body });
  }

  getMetrics() {
    return this.request<DashboardMetrics>('/api/metrics');
  }

  subscribeAlerts(cb: (event: AlertEvent) => void): Unsubscribe {
    return this.listen((m) => m.type === 'alert' && cb(m.data));
  }

  subscribeSuggestions(cb: (s: StaffSuggestion) => void): Unsubscribe {
    return this.listen((m) => m.type === 'suggestion' && cb(m.data));
  }

  subscribeDetections(cameraId: string, cb: (d: Detection[]) => void): Unsubscribe {
    return this.listen((m) => m.type === 'detections' && m.camera_id === cameraId && cb(m.data));
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
          onMessage(JSON.parse(e.data) as WsMessage);
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
