// The dashboard talks to the backend only through this interface. `MockApi` serves demo data
// in the browser; `HttpApi` targets the FastAPI service. Pick one with `VITE_API_URL`.
import type {
  AlertEvent,
  CameraConfig,
  DeviceStatus,
  Metrics,
  Rule,
  StaffSuggestion,
  Zone,
} from '../contracts';

export type Unsubscribe = () => void;

/** One tracked person drawn over the live video (dashboard view model, not an MQTT contract). */
export interface Detection {
  track_id: number;
  role: 'staff' | 'guest';
  /** Normalised [x, y, width, height] in [0,1]. */
  box: [number, number, number, number];
}

/** A camera plus the online state of the device that serves it. */
export interface CameraView extends CameraConfig {
  device: string;
  online: boolean;
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
  listDevices(): Promise<DeviceStatus[]>;
  saveZones(cameraId: string, zones: Zone[]): Promise<Zone[]>;
  listRules(): Promise<Rule[]>;
  createRuleFromText(text: string, cameraId: string): Promise<Rule>;
  listAlerts(): Promise<AlertEvent[]>;
  subscribeAlerts(cb: (event: AlertEvent) => void): Unsubscribe;
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
