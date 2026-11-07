import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { TOAST_MS, ToastContext, type ToastInput } from './toast';

interface Item extends ToastInput {
  id: number;
}

const MAX = 3;

/** Holds the toast stack (bottom right, bottom centre on phones) in one live region. */
export function Toaster({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([]);
  const next = useRef(1);
  const show = useCallback((t: ToastInput) => {
    const id = next.current++;
    setItems((prev) => [...prev, { ...t, id }].slice(-MAX));
  }, []);
  const drop = useCallback((id: number) => setItems((p) => p.filter((t) => t.id !== id)), []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toasts" role="region" aria-label="Notificări">
        {items.map((t) => (
          <Toast key={t.id} toast={t} onDone={() => drop(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function Toast({ toast, onDone }: { toast: Item; onDone: () => void }) {
  const kind = toast.kind ?? 'ok';
  const sticky = toast.sticky ?? kind === 'error';
  const [paused, setPaused] = useState(false);
  const left = useRef(TOAST_MS);
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  });

  useEffect(() => {
    if (sticky || paused) return;
    const started = Date.now();
    const timer = setTimeout(() => done.current(), left.current);
    return () => {
      clearTimeout(timer);
      left.current -= Date.now() - started;
    };
  }, [sticky, paused]);

  return (
    <div
      className={`toast toast-${kind}`}
      role={kind === 'error' ? 'alert' : 'status'}
      onPointerEnter={() => setPaused(true)}
      onPointerLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <span className="toast-dot" aria-hidden="true" />
      <div className="toast-body">
        <strong>{toast.title}</strong>
        {toast.text && <span>{toast.text}</span>}
      </div>
      {toast.action && (
        <button
          type="button"
          className="toast-action"
          onClick={() => {
            void toast.action?.run();
            onDone();
          }}
        >
          {toast.action.label}
        </button>
      )}
      <button
        type="button"
        className="toast-close"
        aria-label="Închide notificarea"
        onClick={onDone}
      >
        ×
      </button>
      {!sticky && (
        <span
          className="toast-bar"
          aria-hidden="true"
          style={{
            animationDuration: `${TOAST_MS}ms`,
            animationPlayState: paused ? 'paused' : 'running',
          }}
        />
      )}
    </div>
  );
}
