// The dashboard talks to the backend only through this interface. `MockApi` serves demo data
// in the browser; `HttpApi` targets the FastAPI service. Pick one with `VITE_API_URL`.
import type {
  AlertEvent,
  CameraConfig,
  DetectedTrack,
  DeviceStatus,
  Metrics,
  Rule,
  StaffSuggestion,
  Zone,
} from '../contracts';

export type Unsubscribe = () => void;

/**
 * One tracked person drawn over the live video, as `/ws/events` sends it. Fields come from the
 * edge contract `DetectedTrack`; only the box differs (here `[x, y, width, height]`).
 */
export interface Detection {
  track_id: DetectedTrack['track_id'];
  role: DetectedTrack['role'];
  /** Normalised [x, y, width, height] in [0,1]. */
  box: [number, number, number, number];
  staff_score?: DetectedTrack['staff_score'];
  raised_hand?: boolean;
}

/** A camera plus the online state of the device that serves it. */
export interface CameraView extends CameraConfig {
  device: string;
  online: boolean;
}

/** What the "Adaugă cameră" form sends. `id` must match the edge's CAMERA_ID. */
export interface NewCamera {
  id: string;
  name: string;
  source: string;
  device: string;
}

/** An alert event as the API serves it: `snapshot_url` is absolute (or null). */
export interface AlertView extends AlertEvent {
  device_id?: string;
  snapshot_url?: string | null;
}

/** A rule drafted from Romanian text; not saved until the user confirms it. */
export interface RuleDraft {
  rule: Rule;
  explanation_ro: string;
}

/** A backend error with the Romanian message the dashboard shows as is. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(messageRo: string, code = 'error', status = 0) {
    super(messageRo);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

/** Aggregated numbers for the metrics strip; `devices` holds the raw per-device Metrics. */
export interface DashboardMetrics {
  devices: Metrics[];
  devices_online: number;
  devices_total: number;
  events_today: number;
  /** Median frame-to-alert latency in milliseconds, null when unknown. */
  alert_latency_ms: number | null;
}

export interface ApiClient {
  readonly kind: 'mock' | 'http';
  listCameras(): Promise<CameraView[]>;
  createCamera(camera: NewCamera): Promise<CameraView>;
  listDevices(): Promise<DeviceStatus[]>;
  saveZones(cameraId: string, zones: Zone[]): Promise<Zone[]>;
  listRules(): Promise<Rule[]>;
  /** Translate a Romanian request into a draft rule; nothing is saved. */
  draftRuleFromText(text: string, cameraId: string): Promise<RuleDraft>;
  /** Save (and publish to the edge) a rule, usually a confirmed draft. */
  createRule(rule: Rule): Promise<Rule>;
  listAlerts(): Promise<AlertView[]>;
  subscribeAlerts(cb: (event: AlertView) => void): Unsubscribe;
  listSuggestions(): Promise<StaffSuggestion[]>;
  subscribeSuggestions(cb: (s: StaffSuggestion) => void): Unsubscribe;
  subscribeDetections(cameraId: string, cb: (d: Detection[]) => void): Unsubscribe;
  confirmSuggestion(id: string): Promise<void>;
  rejectSuggestion(id: string): Promise<void>;
  uploadStaffPhoto(file: File): Promise<void>;
  getMetrics(): Promise<DashboardMetrics>;
}

export async function createApi(baseUrl = import.meta.env.VITE_API_URL): Promise<ApiClient> {
  if (baseUrl) {
    const { HttpApi } = await import('./http');
    return new HttpApi(baseUrl);
  }
  const { MockApi } = await import('./mock');
  return new MockApi();
}
