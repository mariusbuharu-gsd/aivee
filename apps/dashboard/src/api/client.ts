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
  Verification,
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

/** A staff appearance profile built from uniform photos (`GET /api/staff/profiles`). */
export interface StaffProfile {
  id: string;
  name: string;
  description_ro: string;
  /** How many photos (or video frames) the profile was built from. */
  examples: number;
  has_centroid: boolean;
}

/** One guided capture (`POST /api/staff/capture`): the largest person of each sampled frame. */
export interface StaffCapture {
  token: string;
  camera_id: string;
  /** Frames sampled from the camera. */
  frames: number;
  /** `thumbnail` is a `data:image/jpeg;base64,…` URL of the person crop. */
  candidates: { index: number; thumbnail: string }[];
  expires_in_s: number;
}

/** Keep `keep` of a capture: into `profile_id`, or a new profile named `name`. */
export interface StaffCaptureConfirm {
  keep: number[];
  name?: string;
  description_ro?: string;
  profile_id?: string;
}

export interface StaffEnrolResult {
  profile: StaffProfile;
  examples_added: number;
  published: boolean;
}

/** A camera plus the online state of the device that serves it. */
export interface CameraView extends CameraConfig {
  device: string;
  online: boolean;
}

/** `GET /api/devices`: the edge's status plus when the API last heard from it. */
export interface DeviceView extends DeviceStatus {
  site?: string;
  /**
   * ISO time of the last status or metrics message (the edge sends metrics every ~5 s), so
   * while online it is at most a few seconds old; once offline it is when the device went away.
   */
  last_seen?: string | null;
}

/**
 * The newest face-blurred still of a camera (`GET /api/cameras/{id}/frame`). Today it is the
 * whole-frame snapshot of the camera's latest alert, so it can be minutes or hours old: show `at`.
 */
export interface CameraFrame {
  /** Usable as `<img src>`; a `blob:` URL over HTTP, so call `release()` when done with it. */
  url: string;
  /** ISO time the frame was taken, null when unknown. */
  at: string | null;
  release(): void;
}

/** What the "Adaugă cameră" form sends. `id` must match the edge's CAMERA_ID. */
export interface NewCamera {
  id: string;
  name: string;
  source: string;
  device: string;
}

/** `PATCH /api/cameras/{id}`: fields left out stay as they are. */
export type CameraPatch = Partial<Pick<NewCamera, 'name' | 'source' | 'device'>>;

/** `PATCH /api/rules/{id}`: fields left out stay as they are. */
export type RulePatch = Partial<Omit<Rule, 'id' | 'camera_id'>>;

/**
 * A staff suggestion as the API serves it: `snapshot_url` (absolute, or null) is the edge's
 * face-blurred crop of the person. Older APIs omit it; the card then shows a blurred stand-in.
 */
export interface SuggestionView extends StaffSuggestion {
  device_id?: string;
  status?: string;
  snapshot_url?: string | null;
}

/** An alert event as the API serves it: `snapshot_url` is absolute (or null). */
export interface AlertView extends AlertEvent {
  device_id?: string;
  snapshot_url?: string | null;
  /** Who closed it: the edge (someone came) or the system (the camera stopped watching). */
  closed_by?: 'edge' | 'system' | null;
  closed_reason?: 'device_offline' | 'device_restarted' | 'camera_deleted' | null;
  /** The vision model's second opinion; `unavailable` (or absent) means a normal alert. */
  verification?: Verification | null;
  /** `object_gone` only: the frame before the object disappeared; `snapshot_url` is "after". */
  before_snapshot_url?: string | null;
}

/** `PUT /api/cameras/{id}/zones?warnings=true`. */
export interface SavedZones {
  zones: Zone[];
  /** E.g. overlapping zones; saved anyway, shown to the user. */
  warnings_ro: string[];
}

/** `GET /api/rules/stats?days=N`: alerts each rule raised per (UTC) day, oldest day first. */
export interface RuleStats {
  /** ISO dates (`YYYY-MM-DD`), the last N days up to today. */
  days: string[];
  rules: { rule_id: string; total: number; per_day: number[] }[];
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

/** Where an uploaded clip is in the analysis. */
export type VideoStatus = 'queued' | 'running' | 'done' | 'failed';
export type VideoRotation = 0 | 90 | 180 | 270;

/**
 * A clip uploaded for analysis (`/api/videos`). It runs as a virtual camera (`camera_id`) with the
 * zones and rules copied from `source_camera_id`; its alerts never notify the staff.
 */
export interface VideoUpload {
  id: string;
  location_id: string;
  camera_id: string;
  source_camera_id: string | null;
  filename: string;
  size_bytes: number;
  rotate: VideoRotation;
  status: VideoStatus;
  /** 0..1 */
  progress: number;
  duration_s: number | null;
  /** Alerts found so far. */
  events: number;
  error_ro: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  created_by: { id: string; name: string } | null;
}

/** One alert found in a clip; every `*_s` is a position in the clip, in seconds. */
export interface VideoAlert {
  event_id: string;
  zone_id: string;
  zone_name: string;
  summary_ro: string;
  state: 'opened' | 'acknowledged' | 'arrived' | 'closed';
  at_s: number;
  arrived_at_s: number | null;
  closed_at_s: number | null;
  wait_s: number | null;
  /** `video_end` when the clip ended with the alert still open. */
  closed_reason: string | null;
  /** Absolute (resolved against the API) or null. */
  snapshot_url: string | null;
}

/** Same limits as `POST /api/videos`; the dashboard checks the size before uploading. */
export const MAX_VIDEO_BYTES = 200 * 1024 * 1024;
export const VIDEO_TYPES = ['video/mp4', 'video/quicktime', 'video/webm'];

/** What "Analizează un video" sends; the location is the current one (`setLocation`). */
export interface NewVideoUpload {
  file: File;
  rotate?: VideoRotation;
  /** Camera whose zones and rules the clip uses. */
  copy_from_camera_id?: string | null;
}

/** `GET /api/capabilities`: optional features this server runs. */
export interface Capabilities {
  /** Clip analysis ("Testează pe un clip"); false where `POST /api/videos` answers 503. */
  videos: boolean;
  /** Staff profiles (photos, live capture). */
  enrol: boolean;
}

export interface ApiClient extends AccountApi {
  readonly kind: 'mock' | 'http';
  getCapabilities(): Promise<Capabilities>;
  listCameras(): Promise<CameraView[]>;
  createCamera(camera: NewCamera): Promise<CameraView>;
  updateCamera(id: string, patch: CameraPatch): Promise<CameraView>;
  /** Removes the camera with its zones and rules; past alerts stay, open ones close. */
  deleteCamera(id: string): Promise<void>;
  listDevices(): Promise<DeviceView[]>;
  /**
   * The newest face-blurred still of the camera, for a thumbnail or the zone-drawing background.
   * Rejects with an ApiError (404 `not_found` until the camera has sent one).
   */
  captureFrame(cameraId: string): Promise<CameraFrame>;
  /**
   * `GET /api/cameras/{id}/live.mjpg` for an `<img>`: the frames a connector posts over HTTPS
   * (cloud mode). 404 while none came recently. Null when the API has no such stream (mock).
   */
  liveMjpegUrl(cameraId: string): string | null;
  /**
   * `POST /api/ingest/frames/{id}` with the session cookie: one JPEG from the phone page into a
   * cloud camera. Rejects with an ApiError (401 logged out, 403 no `devices.manage`, 409 not a
   * cloud camera, `network` when the request did not get through).
   */
  pushFrame(cameraId: string, jpeg: Blob): Promise<void>;
  saveZones(cameraId: string, zones: Zone[]): Promise<SavedZones>;
  listRules(): Promise<Rule[]>;
  /** Translate a Romanian request into a draft rule; nothing is saved. */
  draftRuleFromText(text: string, cameraId: string): Promise<RuleDraft>;
  /** Save (and publish to the edge) a rule, usually a confirmed draft. */
  createRule(rule: Rule): Promise<Rule>;
  /** Pause/resume (`enabled`) or edit a saved rule; the edge gets the new version. */
  updateRule(id: string, patch: RulePatch): Promise<Rule>;
  deleteRule(id: string): Promise<void>;
  /** Alerts per rule per day over the last `days` days (default 7), current location. */
  getRuleStats(days?: number): Promise<RuleStats>;
  /**
   * `GET /api/events`, newest first. `before` (an ISO time, usually the oldest `at` held) pages
   * back; a page shorter than `limit` (API default 50) is the last.
   */
  listAlerts(query?: AlertPageQuery): Promise<AlertView[]>;
  subscribeAlerts(cb: (event: AlertView) => void): Unsubscribe;
  listSuggestions(): Promise<SuggestionView[]>;
  subscribeSuggestions(cb: (s: SuggestionView) => void): Unsubscribe;
  subscribeDetections(cameraId: string, cb: (d: Detection[]) => void): Unsubscribe;
  confirmSuggestion(id: string): Promise<void>;
  rejectSuggestion(id: string): Promise<void>;
  uploadStaffPhoto(file: File): Promise<void>;
  /**
   * `POST /api/staff/capture` (`staff.enrol`): samples the camera's live frames for `seconds`
   * (5–30, default 20); resolves after about that long. 404 when the camera sends nothing,
   * 422 when nobody was in front of it, 503 without enrolment models.
   */
  captureStaff(cameraId: string, seconds?: number): Promise<StaffCapture>;
  /**
   * `POST /api/staff/capture/frames` (`staff.enrol`, multipart `frames`, ≤ 30 JPEGs of ≤ 2 MB):
   * the same capture from photos this phone took itself; confirm it like a camera capture.
   */
  uploadStaffFrames(frames: Blob[]): Promise<StaffCapture>;
  /** `POST /api/staff/capture/{token}/confirm`: enrol the kept crops and publish the profile. */
  confirmStaffCapture(token: string, input: StaffCaptureConfirm): Promise<StaffEnrolResult>;
  /** `GET /api/staff/profiles` (`staff.enrol`): enrolled uniform profiles, shared by every location. */
  listStaffProfiles(): Promise<StaffProfile[]>;
  getMetrics(): Promise<DashboardMetrics>;
  /** `POST /api/videos` (multipart). 422 for a bad type, size or length. */
  uploadVideo(input: NewVideoUpload): Promise<VideoUpload>;
  /** The current location's uploads, newest first. */
  listVideos(): Promise<VideoUpload[]>;
  getVideo(id: string): Promise<VideoUpload>;
  /** Alerts found in the clip, by position (`at_s`) ascending. */
  videoEvents(id: string): Promise<VideoAlert[]>;
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
  /**
   * The owner's goal for how long a guest may wait for staff after an alert, in seconds
   * (1–3600); null when not set. Owners and managers (`rules.manage`) may change it.
   */
  service_target_s?: number | null;
  /** `GET /api/locations` only: live cameras at the location, and those whose device is online. */
  cameras_total?: number;
  cameras_online?: number;
}

/** "Conectează Telegram" deep links (`POST /api/locations/{id}/telegram/link`), single use. */
export interface TelegramLink {
  /** Adds the bot to a group (`?startgroup=`). */
  url: string;
  /** A private chat with the bot (`?start=`). */
  private_url: string;
  expires_at: string;
}

export interface TelegramStatus {
  connected: boolean;
  chat_title?: string | null;
}

export interface Member {
  user_id: string;
  name: string;
  email: string;
  role: Role;
  /** Has a Web Push subscription: their phone or browser gets the alerts. */
  push_enabled?: boolean;
}

export interface Invite {
  invite_url: string;
  expires_at: string;
}

/** An invite nobody accepted yet (`GET /api/invites`). */
export interface PendingInvite {
  id: string;
  email: string;
  role: Role;
  location_id: string;
  created_by: string;
  created_at: string;
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

/** Paging of `GET /api/events`: rows strictly older than `before` (ISO time), at most `limit`. */
export interface AlertPageQuery {
  before?: string;
  limit?: number;
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
  /** Display name of whoever pressed "Preiau". */
  acknowledged_by: string | null;
  acknowledged_by_id: string | null;
  arrived_at: string | null;
  /** Staff arrived without anyone acknowledging first ("fără preluare"). */
  unacknowledged_arrival: boolean;
  closed_at: string | null;
  /** The shift was reminded: "Preiau" was pressed 2 min earlier and nobody had arrived. */
  realerted_at?: string | null;
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

/** One weekday × hour cell of `GET /api/metrics/service/heatmap`. */
export interface HeatCell {
  alerts: number;
  /** Median wait of the cell's alerts; null when none has one. */
  wait_median_s: number | null;
}

/** When guests wait: alerts and median wait per local weekday and hour (team level only). */
export interface ServiceHeatmap {
  location_id: string | null;
  from: string | null;
  to: string | null;
  /** IANA zone the weekdays and hours are counted in (Europe/Bucharest). */
  timezone: string;
  /** 7 rows, Monday first, of 24 hourly cells (00–23). */
  cells: HeatCell[][];
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
  /** A 15-minute single-use link; `locations.manage`. 503 when the server has no bot. */
  createTelegramLink(locationId: string): Promise<TelegramLink>;
  getTelegramStatus(locationId: string): Promise<TelegramStatus>;
  listMembers(locationId: string): Promise<Member[]>;
  updateMember(locationId: string, userId: string, role: Role): Promise<Member>;
  removeMember(locationId: string, userId: string): Promise<void>;
  createInvite(input: { location_id: string; role: Role; email: string }): Promise<Invite>;
  /** Pending invites; a manager sees only staff invites. */
  listInvites(locationId: string): Promise<PendingInvite[]>;
  /** Idempotent; the link then answers 410. */
  revokeInvite(id: string): Promise<void>;
  listAudit(query: AuditQuery): Promise<AuditPage>;
  /** `GET /api/alerts`, newest first; `before` = only alerts opened before that ISO time. */
  listAlertCases(query: {
    location_id: string;
    state?: string;
    limit?: number;
    before?: string;
  }): Promise<AlertCase[]>;
  /** "Preiau". 409 when someone already took it. */
  ackAlert(eventId: string): Promise<AlertCase>;
  getServiceMetrics(query: {
    location_id: string;
    from?: string;
    to?: string;
  }): Promise<ServiceMetrics>;
  getServiceHeatmap(query: {
    location_id: string;
    from?: string;
    to?: string;
  }): Promise<ServiceHeatmap>;
}

/** Fired on window when the API answers 401, so the app can return to /intra. */
export const UNAUTHORIZED_EVENT = 'aivee:unauthorized';
