import { createContext, useContext } from 'react';
import type {
  AlertCase,
  AlertView,
  CameraView,
  DashboardMetrics,
  SuggestionView,
} from '../api/client';
import type { AlertItem } from '../alerts/fold';
import type { Rule, Zone } from '../contracts';

/** Why the shared data failed to load: the banner says something different for each. */
export interface LoadError {
  kind: 'network' | 'forbidden' | 'other';
  message: string;
}

export interface LiveData {
  cameras: CameraView[];
  rules: Rule[];
  events: AlertView[];
  /** `events` folded into opened/closed alerts, newest first. */
  alerts: AlertItem[];
  suggestions: SuggestionView[];
  metrics: DashboardMetrics | null;
  error: LoadError | null;
  loading: boolean;
  /** Load everything again (the banner's "Încearcă acum"). */
  retry: () => void;
  setZones: (cameraId: string, zones: Zone[]) => void;
  /** Add a rule or replace it in place (same id). */
  addRule: (rule: Rule) => void;
  removeRule: (id: string) => void;
  /** Add a camera or replace it in place (same id). */
  addCamera: (camera: CameraView) => void;
  /** Drop a deleted camera and its rules. */
  removeCamera: (id: string) => void;
  dropSuggestion: (id: string) => void;
  /** Lifecycle per alert, keyed by the opening event id (AlertItem.key). */
  cases: Record<string, AlertCase>;
  /** "Preiau": acknowledge an open alert; rejects with the API's Romanian message. */
  ack: (eventId: string) => Promise<void>;
  /** True while the API may hold events older than the ones loaded (the last page was full). */
  hasOlder: boolean;
  /** Load the next page of older events (and their lifecycles) into `events`. */
  loadOlder: () => Promise<void>;
  /** The zone's name for an alert row; never the raw id (see `zoneName`). */
  zoneName: (zoneId: string) => string;
}

export const LiveDataContext = createContext<LiveData | null>(null);

export function useLiveData(): LiveData {
  const v = useContext(LiveDataContext);
  if (!v) throw new Error('useLiveData must be used inside <LiveDataProvider>');
  return v;
}

/** Shown for a zone nobody knows the name of any more (never the raw id). */
export const UNKNOWN_ZONE = 'Zonă ștearsă';

/**
 * Zone name lookup across the location's cameras, then the names the API sent with the alerts
 * (`known`: zone id → name), so an alert of a redrawn or deleted zone keeps a readable name.
 */
export function zoneName(
  cameras: CameraView[],
  zoneId: string,
  known: Readonly<Record<string, string>> = {},
): string {
  for (const c of cameras) {
    const z = c.zones?.find((x) => x.id === zoneId);
    if (z) return z.name;
  }
  return known[zoneId] ?? UNKNOWN_ZONE;
}

/**
 * Whether a live alert belongs to the location on screen. The socket streams every location
 * the user may see: folded updates name their location; raw event rows don't, so their camera
 * must be one of this location's.
 */
export function belongsHere(
  e: Pick<AlertView, 'location_id' | 'camera_id'>,
  locationId: string | null,
  cameraIds: ReadonlySet<string>,
): boolean {
  if (e.location_id != null) return e.location_id === locationId;
  return cameraIds.has(e.camera_id);
}

/** Network failures and missing permissions are told apart from other errors. */
export function toLoadError(e: unknown): LoadError {
  const message = e instanceof Error ? e.message : String(e);
  const status = (e as { status?: unknown } | null)?.status;
  const code = (e as { code?: unknown } | null)?.code;
  if (code === 'network') return { kind: 'network', message };
  if (status === 403) return { kind: 'forbidden', message };
  return { kind: 'other', message };
}
