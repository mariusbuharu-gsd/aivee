import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Icon, type IconName } from '../components/Icon';
import { Banner } from './Banner';

/**
 * A modal on the native `<dialog>`: focus is trapped, Esc and a click on the backdrop close it,
 * focus returns to whatever opened it. Render it only while it should be open.
 */
export function Dialog({
  title,
  icon,
  tone = 'neutral',
  onClose,
  children,
  actions,
  className = '',
}: {
  title: string;
  icon?: IconName;
  tone?: 'neutral' | 'danger';
  onClose: () => void;
  children?: ReactNode;
  actions: ReactNode;
  /** `dialog-sheet` docks it to the bottom on phones. */
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    const opener = document.activeElement as HTMLElement | null;
    if (!d.open) d.showModal();
    // Start on the safe choice (or the first field), never on the destructive button.
    d.querySelector<HTMLElement>('[data-autofocus]')?.focus();
    const onCancel = (e: Event) => {
      e.preventDefault();
      closeRef.current();
    };
    d.addEventListener('cancel', onCancel);
    return () => {
      d.removeEventListener('cancel', onCancel);
      if (d.open) d.close();
      opener?.focus?.();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      className={`dialog ${className}`}
      aria-labelledby={titleId}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="dialog-body">
        {icon && (
          <span
            className={`dialog-icon ${tone === 'danger' ? 'is-danger' : ''}`}
            aria-hidden="true"
          >
            <Icon name={icon} size={22} />
          </span>
        )}
        <h2 id={titleId} className="dialog-title">
          {title}
        </h2>
        {children}
        <div className="dialog-actions">{actions}</div>
      </div>
    </dialog>
  );
}

/**
 * "Are you sure?" done right: the title is the question, the body says what happens, the button
 * repeats the verb. With `confirmText` the user must type it (for deleting a whole location).
 * The dialog stays open and shows the error when `onConfirm` rejects.
 */
export function ConfirmDialog({
  title,
  icon = 'trash',
  tone = 'danger',
  confirmLabel,
  cancelLabel = 'Renunță',
  confirmText,
  onConfirm,
  onClose,
  children,
}: {
  title: string;
  icon?: IconName;
  tone?: 'neutral' | 'danger';
  confirmLabel: string;
  cancelLabel?: string;
  confirmText?: string;
  onConfirm: () => Promise<unknown> | unknown;
  onClose: () => void;
  children?: ReactNode;
}) {
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputId = useId();
  const ready = !confirmText || typed.trim() === confirmText;

  async function go() {
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Nu a mers. Încearcă din nou.');
      setBusy(false);
    }
  }

  return (
    <Dialog
      title={title}
      icon={icon}
      tone={tone}
      onClose={() => !busy && onClose()}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy} data-autofocus>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`btn ${tone === 'danger' ? 'btn-danger-solid' : 'btn-primary'}`}
            onClick={() => void go()}
            disabled={!ready || busy}
          >
            {busy ? 'Un moment…' : confirmLabel}
          </button>
        </>
      }
    >
      {children}
      {confirmText && (
        <label className="field" htmlFor={inputId}>
          <span>
            Scrie <strong>{confirmText}</strong> ca să confirmi
          </span>
          <input
            id={inputId}
            className="input"
            autoComplete="off"
            data-autofocus
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void go();
            }}
          />
        </label>
      )}
      {error && <Banner tone="error" title={error} />}
    </Dialog>
  );
}
