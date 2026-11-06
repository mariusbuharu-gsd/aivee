import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import type { CameraView, DashboardMetrics } from '../api/client';
import { useApi } from '../api/context';
import type { AlertEvent, Rule, StaffSuggestion, Zone } from '../contracts';
import { foldAlerts } from '../alerts/fold';
import { LiveDataContext, type LiveData } from './context';

const METRICS_POLL_MS = 5_000;

/** Loads shared dashboard state once and keeps it fresh from the API's subscriptions. */
export function LiveDataProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const [cameras, setCameras] = useState<CameraView[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [suggestions, setSuggestions] = useState<StaffSuggestion[]>([]);
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const fail = (e: unknown) => alive && setError(e instanceof Error ? e.message : String(e));
    Promise.all([
      api.listCameras(),
      api.listRules(),
      api.listAlerts(),
      api.listSuggestions(),
      api.getMetrics(),
    ])
      .then(([c, r, a, s, m]) => {
        if (!alive) return;
        setCameras(c);
        setRules(r);
        setEvents((prev) => [...a, ...prev]);
        setSuggestions((prev) => mergeSuggestions(s, prev));
        setMetrics(m);
      })
      .catch(fail)
      .finally(() => alive && setLoading(false));

    const offAlerts = api.subscribeAlerts((e) => setEvents((prev) => [...prev, e]));
    const offSuggestions = api.subscribeSuggestions((s) =>
      setSuggestions((prev) => mergeSuggestions(prev, [s])),
    );
    const poll = setInterval(() => {
      api.getMetrics().then((m) => alive && setMetrics(m), fail);
    }, METRICS_POLL_MS);
    return () => {
      alive = false;
      offAlerts();
      offSuggestions();
      clearInterval(poll);
    };
  }, [api]);

  const setZones = useCallback(
    (cameraId: string, zones: Zone[]) =>
      setCameras((prev) => prev.map((c) => (c.id === cameraId ? { ...c, zones } : c))),
    [],
  );
  const addRule = useCallback((r: Rule) => setRules((prev) => [...prev, r]), []);
  const dropSuggestion = useCallback(
    (id: string) => setSuggestions((prev) => prev.filter((s) => s.suggestion_id !== id)),
    [],
  );

  const alerts = useMemo(() => foldAlerts(events), [events]);

  const value = useMemo<LiveData>(
    () => ({
      cameras,
      rules,
      events,
      alerts,
      suggestions,
      metrics,
      error,
      loading,
      setZones,
      addRule,
      dropSuggestion,
    }),
    [
      cameras,
      rules,
      events,
      alerts,
      suggestions,
      metrics,
      error,
      loading,
      setZones,
      addRule,
      dropSuggestion,
    ],
  );
  return <LiveDataContext.Provider value={value}>{children}</LiveDataContext.Provider>;
}

function mergeSuggestions(a: StaffSuggestion[], b: StaffSuggestion[]): StaffSuggestion[] {
  const out = [...a];
  for (const s of b) if (!out.some((x) => x.suggestion_id === s.suggestion_id)) out.push(s);
  return out;
}
