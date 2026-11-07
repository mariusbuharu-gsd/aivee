import { createContext, useContext } from 'react';

export type ToastKind = 'ok' | 'info' | 'error' | 'undo';

export interface ToastInput {
  title: string;
  text?: string;
  kind?: ToastKind;
  /** One action, e.g. "Anulează" or "Reîncearcă"; the toast closes after it runs. */
  action?: { label: string; run: () => unknown };
  /** Stays until closed (errors are sticky by default). */
  sticky?: boolean;
}

export type ShowToast = (t: ToastInput) => void;

/** Outside a <Toaster> toasts are dropped, so isolated component tests need no provider. */
export const ToastContext = createContext<ShowToast>(() => undefined);

/** The result of an action the user just took: "Zonele s-au salvat", "Link copiat". */
export function useToast(): ShowToast {
  return useContext(ToastContext);
}

export const TOAST_MS = 5_000;
