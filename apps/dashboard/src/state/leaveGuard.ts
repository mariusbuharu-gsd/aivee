import { createContext, useContext, useEffect, useRef } from 'react';

/**
 * Asked before the app leaves the current page (a nav link, the location switch).
 * Return true to hold the navigation; call `proceed` later to let it go on.
 */
export type LeaveGuard = (proceed: () => void) => boolean;

export interface LeaveGuardApi {
  set: (guard: LeaveGuard | null) => void;
  /** Runs `go` now, or later if the current page holds it. */
  leave: (go: () => void) => void;
}

export const LeaveGuardContext = createContext<LeaveGuardApi>({
  set: () => undefined,
  leave: (go) => go(),
});

export const useLeave = () => useContext(LeaveGuardContext).leave;

/** While `guard` is set, in-app navigation asks it first and closing the tab warns. */
export function useLeaveGuard(guard: LeaveGuard | null) {
  const { set } = useContext(LeaveGuardContext);
  const latest = useRef(guard);
  useEffect(() => {
    latest.current = guard;
  });
  const active = guard !== null;
  useEffect(() => {
    if (!active) return;
    set((proceed) => latest.current?.(proceed) ?? false);
    const onUnload = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', onUnload);
    return () => {
      set(null);
      window.removeEventListener('beforeunload', onUnload);
    };
  }, [active, set]);
}
