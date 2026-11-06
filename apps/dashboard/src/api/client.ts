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

export interface ApiClient extends AccountApi {
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

// ---------------------------------------------------------------------------------------------
// Accounts, locations, audit history and the alert lifecycle.
// Contract: docs/plans/2026-11-06-auth-roles-audit.md (decisions D19–D24).

export type Role = 'owner' | 'manager' | 'staff';
export type Permission =
  | 'alerts.view'
  | 'alerts.ack'
  | 'staff.review'
  | 'staff.enrol'
  | 'rules.manage'
  | 'devices.manage'
  | 'users.manage'
  | 'locations.manage'
  | 'audit.view'
  | 'audit.view.own';
export type LocationType = 'restaurant' | 'terrace' | 'event' | 'shop' | 'other';

export interface MeLocation {
  id: string;
  name: string;
  type: string;
  role: Role;
  permissions: string[];
}

export interface Me {
  user: { id: string; name: string; email: string };
  org: { id: string; name: string };
  is_owner: boolean;
  locations: MeLocation[];
}

export interface RegisterInput {
  org_name: string;
  name: string;
  email: string;
  password: string;
}

export interface Location {
  id: string;
  name: string;
  type: string;
  telegram_chat_id?: string | null;
}

export interface Member {
  user_id: string;
  name: string;
  email: string;
  role: Role;
}

export interface Invite {
  invite_url: string;
  expires_at: string;
}

export interface InviteInfo {
  org_name: string;
  location_name: string;
  role: Role;
  email: string;
}

export interface AuditEntry {
  id: string;
  at: string;
  location_id: string | null;
  actor: { kind: 'user' | 'device' | 'system'; id: string; name: string };
  kind: string;
  target: { type: string; id: string; label: string } | null;
  summary_ro: string;
  before: unknown;
  after: unknown;
}

export interface AuditQuery {
  location_id: string;
  actor?: string;
  /** An exact kind ("rule.updated") or a family ("rule" matches every `rule.*`). */
  kind?: string;
  /** Entry id from `next_before`; only entries older than it (paging). */
  before?: string;
  /** ISO time; only entries at or after it (period filter). */
  from?: string;
  /** ISO time; only entries before it. */
  to?: string;
  limit?: number;
}

export interface AuditPage {
  items: AuditEntry[];
  next_before: string | null;
}

/** One alert folded over its lifecycle: opened → acknowledged → arrived → closed. */
export interface AlertCase {
  event_id: string;
  rule_id: string;
  location_id: string;
  camera_id: string;
  zone_id: string;
  zone_name: string;
  summary_ro: string;
  opened_at: string;
  acknowledged_at: string | null;
  /** Display name of whoever pressed "Merg eu". */
  acknowledged_by: string | null;
  acknowledged_by_id: string | null;
  arrived_at: string | null;
  /** Staff arrived without anyone acknowledging first ("fără preluare"). */
  unacknowledged_arrival: boolean;
  closed_at: string | null;
  wait_s: number | null;
  reaction_s: number | null;
  travel_s: number | null;
}

export interface DurationStat {
  median_s: number | null;
  p90_s: number | null;
  /** How many alerts the measure is based on. */
  count: number;
}

/** `GET /api/metrics/service`: how long guests wait and how fast the team reacts. */
export interface ServiceMetrics {
  location_id: string;
  from: string | null;
  to: string | null;
  alerts: number;
  wait: DurationStat;
  reaction: DurationStat;
  travel: DurationStat;
}

export interface AccountApi {
  me(): Promise<Me>;
  login(email: string, password: string): Promise<Me>;
  register(input: RegisterInput): Promise<Me>;
  logout(): Promise<void>;
  getInvite(token: string): Promise<InviteInfo>;
  acceptInvite(token: string, input: { name: string; password: string }): Promise<Me>;
  /** The location the other calls are scoped to (`location_id`); null = the API default. */
  setLocation(locationId: string | null): void;
  listLocations(): Promise<Location[]>;
  createLocation(location: Location): Promise<Location>;
  updateLocation(id: string, patch: Partial<Omit<Location, 'id'>>): Promise<Location>;
  deleteLocation(id: string): Promise<void>;
  listMembers(locationId: string): Promise<Member[]>;
  updateMember(locationId: string, userId: string, role: Role): Promise<Member>;
  removeMember(locationId: string, userId: string): Promise<void>;
  createInvite(input: { location_id: string; role: Role; email: string }): Promise<Invite>;
  listAudit(query: AuditQuery): Promise<AuditPage>;
  listAlertCases(query: {
    location_id: string;
    state?: string;
    limit?: number;
  }): Promise<AlertCase[]>;
  /** "Merg eu". 409 when someone already took it. */
  ackAlert(eventId: string): Promise<AlertCase>;
  getServiceMetrics(query: {
    location_id: string;
    from?: string;
    to?: string;
  }): Promise<ServiceMetrics>;
}

/** Fired on window when the API answers 401, so the app can return to /intra. */
export const UNAUTHORIZED_EVENT = 'aivee:unauthorized';
