import { createContext, useContext } from 'react';
import type { AlertCase, AlertView, CameraView, DashboardMetrics } from '../api/client';
import type { AlertItem } from '../alerts/fold';
import type { Rule, StaffSuggestion, Zone } from '../contracts';

export interface LiveData {
  cameras: CameraView[];
  rules: Rule[];
  events: AlertView[];
  /** `events` folded into opened/closed alerts, newest first. */
  alerts: AlertItem[];
  suggestions: StaffSuggestion[];
  metrics: DashboardMetrics | null;
  error: string | null;
  loading: boolean;
  setZones: (cameraId: string, zones: Zone[]) => void;
  addRule: (rule: Rule) => void;
  addCamera: (camera: CameraView) => void;
  dropSuggestion: (id: string) => void;
  /** Lifecycle per alert, keyed by the opening event id (AlertItem.key). */
  cases: Record<string, AlertCase>;
  /** "Merg eu": acknowledge an open alert; rejects with the API's Romanian message. */
  ack: (eventId: string) => Promise<void>;
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
