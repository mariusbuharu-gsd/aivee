import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type {
  AlertCase,
  AlertView,
  CameraView,
  DashboardMetrics,
  SuggestionView,
} from '../api/client';
import { useApi } from '../api/context';
import { useAuth } from '../auth/context';
import type { Rule, Zone } from '../contracts';
import { foldAlerts } from '../alerts/fold';
import {
  LiveDataContext,
  belongsHere,
  toLoadError,
  zoneName,
  type LiveData,
  type LoadError,
} from './context';

const METRICS_POLL_MS = 5_000;
/** A reconnect and a wake-up often come together: one reload for both. */
const RESYNC_DEBOUNCE_MS = 300;
const noop = () => undefined;
/** Events per `GET /api/events` page (the API's default); a full page means older ones exist. */
const EVENTS_PAGE = 50;
const CASES_PAGE = 100;

/** Loads shared dashboard state once and keeps it fresh from the API's subscriptions. */
export function LiveDataProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const [cameras, setCameras] = useState<CameraView[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [events, setEvents] = useState<AlertView[]>([]);
  const [suggestions, setSuggestions] = useState<SuggestionView[]>([]);
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [error, setError] = useState<LoadError | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  const [hasOlder, setHasOlder] = useState(false);
  const { location, can } = useAuth();
  const locationId = location?.id ?? null;
  const canView = can('alerts.view');
  // Staff get 403 on every /api/rules* call, so they never ask for rules.
  const canRules = can('rules.manage');
  // Suggestions are staff.review only; staff get 403, which used to fail the whole first load.
  const canReview = can('staff.review');
  const [cases, setCases] = useState<Record<string, AlertCase>>({});
  // The socket carries every location the user may see; raw rows are told apart by camera.
  // Until this location's cameras are known, those rows wait here (`null` = cameras loaded).
  const cameraIds = useRef<Set<string>>(new Set());
  const unsorted = useRef<AlertView[] | null>([]);
  useEffect(() => {
    cameraIds.current = new Set(cameras.map((c) => c.id));
  }, [cameras]);

  // Alert lifecycle: load once, then re-read whenever an alert event arrives (opened/arrived/closed).
  useEffect(() => {
    if (!locationId || !canView) return;
    let alive = true;
    let pending: ReturnType<typeof setTimeout> | undefined;
    // Merged, not replaced: older pages loaded by `loadOlder` keep their lifecycles.
    const load = () =>
      api.listAlertCases({ location_id: locationId, limit: CASES_PAGE }).then(
        (rows) => alive && setCases((prev) => ({ ...prev, ...byEventId(rows) })),
        () => undefined,
      );
    void load();
    const off = api.subscribeAlerts((e) => {
      if (e.location_id != null && e.location_id !== locationId) return;
      clearTimeout(pending);
      pending = setTimeout(load, 300);
    });
    return () => {
      alive = false;
      clearTimeout(pending);
      off();
    };
  }, [api, locationId, canView]);

  // After the socket comes back, or the phone wakes the tab, updates may have been missed (a
  // closed alert would stay open on a waiter's screen): read alerts, cameras and suggestions again.
  useEffect(() => {
    let alive = true;
    let pending: ReturnType<typeof setTimeout> | undefined;
    const resync = () => {
      clearTimeout(pending);
      pending = setTimeout(() => {
        void api.listCameras().then((c) => alive && setCameras(c), noop);
        void api
          .listAlerts({ limit: EVENTS_PAGE })
          .then((a) => alive && setEvents((prev) => mergeEvents(a, prev)), noop);
        if (locationId && canView) {
          void api
            .listAlertCases({ location_id: locationId, limit: CASES_PAGE })
            .then((rows) => alive && setCases((prev) => ({ ...prev, ...byEventId(rows) })), noop);
        }
        if (canReview) {
          void api.listSuggestions().then((s) => alive && setSuggestions(s), noop);
        }
      }, RESYNC_DEBOUNCE_MS);
    };
    const onVisible = () => {
      if (document.visibilityState === 'visible') resync();
    };
    const off = api.subscribeReconnect(resync);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      alive = false;
      clearTimeout(pending);
      off();
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [api, locationId, canView, canReview]);

  const ack = useCallback(
    async (eventId: string) => {
      const c = await api.ackAlert(eventId);
      setCases((prev) => ({ ...prev, [c.event_id]: c }));
    },
    [api],
  );

  useEffect(() => {
    let alive = true;
    const fail = (e: unknown) => alive && setError(toLoadError(e));
    Promise.all([
      api.listCameras(),
      canRules ? api.listRules() : Promise.resolve([]),
      api.listAlerts({ limit: EVENTS_PAGE }),
      canReview ? api.listSuggestions() : Promise.resolve([]),
      api.getMetrics(),
    ])
      .then(([c, r, a, s, m]) => {
        if (!alive) return;
        setError(null);
        setCameras(c);
        const ids = new Set(c.map((x) => x.id));
        cameraIds.current = ids;
        const waiting = (unsorted.current ?? []).filter((e) => belongsHere(e, locationId, ids));
        unsorted.current = null;
        setRules(r);
        setEvents((prev) => mergeEvents(a, [...prev, ...waiting]));
        setHasOlder(a.length >= EVENTS_PAGE);
        setSuggestions((prev) => mergeSuggestions(s, prev));
        setMetrics(m);
      })
      .catch(fail)
      .finally(() => alive && setLoading(false));

    const offAlerts = api.subscribeAlerts((e) => {
      if (e.location_id == null && unsorted.current) {
        unsorted.current.push(e);
        return;
      }
      if (belongsHere(e, locationId, cameraIds.current)) setEvents((prev) => [...prev, e]);
    });
    const offSuggestions = api.subscribeSuggestions((s) =>
      setSuggestions((prev) => mergeSuggestions(prev, [s])),
    );
    const poll = setInterval(() => {
      api.getMetrics().then((m) => {
        if (!alive) return;
        setMetrics(m);
        setError((prev) => (prev?.kind === 'network' ? null : prev));
      }, fail);
    }, METRICS_POLL_MS);
    return () => {
      alive = false;
      offAlerts();
      offSuggestions();
      clearInterval(poll);
    };
  }, [api, canRules, canReview, attempt, locationId]);

  const retry = useCallback(() => {
    setLoading(true);
    setAttempt((n) => n + 1);
  }, []);

  const setZones = useCallback(
    (cameraId: string, zones: Zone[]) =>
      setCameras((prev) => prev.map((c) => (c.id === cameraId ? { ...c, zones } : c))),
    [],
  );
  const addRule = useCallback((r: Rule) => setRules((prev) => upsert(prev, r)), []);
  const removeRule = useCallback(
    (id: string) => setRules((prev) => prev.filter((r) => r.id !== id)),
    [],
  );
  const addCamera = useCallback(
    (c: CameraView) =>
      setCameras((prev) =>
        upsert(prev, { ...prev.find((x) => x.id === c.id), ...c } as CameraView),
      ),
    [],
  );
  const removeCamera = useCallback((id: string) => {
    setCameras((prev) => prev.filter((c) => c.id !== id));
    setRules((prev) => prev.filter((r) => r.camera_id !== id));
  }, []);
  const dropSuggestion = useCallback(
    (id: string) => setSuggestions((prev) => prev.filter((s) => s.suggestion_id !== id)),
    [],
  );

  const loadingOlder = useRef(false);
  /** One page before the oldest event held; the lifecycles of alerts opened before it too. */
  const loadOlder = useCallback(async () => {
    if (loadingOlder.current) return;
    const oldest = events.reduce<string | null>(
      (min, e) => (min === null || e.at < min ? e.at : min),
      null,
    );
    if (oldest === null) return;
    loadingOlder.current = true;
    try {
      const [page, older] = await Promise.all([
        api.listAlerts({ before: oldest, limit: EVENTS_PAGE }),
        locationId && canView
          ? api
              .listAlertCases({ location_id: locationId, before: oldest, limit: CASES_PAGE })
              .catch(() => [])
          : Promise.resolve([]),
      ]);
      setEvents((prev) => mergeEvents(prev, page));
      setCases((prev) => ({ ...byEventId(older), ...prev }));
      setHasOlder(page.length >= EVENTS_PAGE);
    } finally {
      loadingOlder.current = false;
    }
  }, [api, events, locationId, canView]);

  // The lifecycle is the API's word: an alert it closed is closed here too, even when the
  // `closed` event itself was never received.
  const alerts = useMemo(
    () =>
      foldAlerts(events).map((a) => {
        const closedAt = cases[a.key]?.closed_at;
        return a.closed_at === null && closedAt ? { ...a, closed_at: closedAt } : a;
      }),
    [events, cases],
  );

  const knownZones = useMemo(() => {
    const out: Record<string, string> = {};
    for (const c of Object.values(cases)) if (c.zone_name) out[c.zone_id] = c.zone_name;
    for (const a of alerts) if (a.zone_name) out[a.zone_id] = a.zone_name;
    return out;
  }, [cases, alerts]);
  const nameOfZone = useCallback(
    (zoneId: string) => zoneName(cameras, zoneId, knownZones),
    [cameras, knownZones],
  );

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
      retry,
      setZones,
      addRule,
      removeRule,
      addCamera,
      removeCamera,
      dropSuggestion,
      cases,
      ack,
      hasOlder,
      loadOlder,
      zoneName: nameOfZone,
    }),
    [
      nameOfZone,
      cases,
      ack,
      hasOlder,
      loadOlder,
      cameras,
      rules,
      events,
      alerts,
      suggestions,
      metrics,
      error,
      loading,
      retry,
      setZones,
      addRule,
      removeRule,
      addCamera,
      removeCamera,
      dropSuggestion,
    ],
  );
  return <LiveDataContext.Provider value={value}>{children}</LiveDataContext.Provider>;
}

function mergeSuggestions(a: SuggestionView[], b: SuggestionView[]): SuggestionView[] {
  const out = [...a];
  for (const s of b) if (!out.some((x) => x.suggestion_id === s.suggestion_id)) out.push(s);
  return out;
}

/** Replace an item with the same id where it is, or append it. */
function upsert<T extends { id: string }>(list: T[], item: T): T[] {
  return list.some((x) => x.id === item.id)
    ? list.map((x) => (x.id === item.id ? item : x))
    : [...list, item];
}

/** A retry loads the history again: keep each event once. */
function mergeEvents(loaded: AlertView[], live: AlertView[]): AlertView[] {
  const seen = new Set(loaded.map((e) => e.event_id));
  return [...loaded, ...live.filter((e) => !seen.has(e.event_id))];
}

function byEventId(rows: AlertCase[]): Record<string, AlertCase> {
  return Object.fromEntries(rows.map((c) => [c.event_id, c]));
}
