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
}

export const LiveDataContext = createContext<LiveData | null>(null);

export function useLiveData(): LiveData {
  const v = useContext(LiveDataContext);
  if (!v) throw new Error('useLiveData must be used inside <LiveDataProvider>');
  return v;
}

/** Zone name lookup across all cameras, falling back to the raw id. */
export function zoneName(cameras: CameraView[], zoneId: string): string {
  for (const c of cameras) {
    const z = c.zones?.find((x) => x.id === zoneId);
    if (z) return z.name;
  }
  return zoneId;
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
