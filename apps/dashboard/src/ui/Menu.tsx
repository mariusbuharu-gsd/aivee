import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { Icon } from '../components/Icon';

export interface MenuItem {
  label: string;
  onSelect: () => void;
  /** Destructive: shown last, in red, after a divider. End the label with "…" if it asks first. */
  danger?: boolean;
  disabled?: boolean;
}

/** The "⋯" actions menu for a row or a card (WAI-ARIA menu button). */
export function Menu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const id = useId();
  const safe = items.filter((i) => !i.danger);
  const danger = items.filter((i) => i.danger);
  const ordered = [...safe, ...danger];

  useEffect(() => {
    if (!open) return;
    list.current?.querySelector<HTMLButtonElement>('[role=menuitem]:not(:disabled)')?.focus();
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [open]);

  function close(focus = true) {
    setOpen(false);
    if (focus) button.current?.focus();
  }

  function onKey(e: KeyboardEvent) {
    const els = [...(list.current?.querySelectorAll<HTMLButtonElement>('[role=menuitem]') ?? [])];
    const i = els.indexOf(document.activeElement as HTMLButtonElement);
    const move = (to: number) => els[(to + els.length) % els.length]?.focus();
    const keys: Record<string, () => void> = {
      ArrowDown: () => move(i + 1),
      ArrowUp: () => move(i - 1),
      Home: () => move(0),
      End: () => move(els.length - 1),
      Escape: () => close(),
    };
    if (e.key === 'Tab') return close(false);
    const run = keys[e.key];
    if (!run) return;
    e.preventDefault();
    run();
  }

  return (
    <div className="menu-wrap" ref={root}>
      <button
        ref={button}
        type="button"
        className="btn btn-ghost btn-sm btn-icon"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' && !open) {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        <Icon name="dots" />
      </button>
      {open && (
        <ul ref={list} id={id} role="menu" aria-label={label} className="menu" onKeyDown={onKey}>
          {ordered.map((item, i) => (
            <li key={item.label} role="none">
              {item.danger && i === safe.length && safe.length > 0 && <hr className="menu-sep" />}
              <button
                type="button"
                role="menuitem"
                className={item.danger ? 'is-danger' : undefined}
                disabled={item.disabled}
                onClick={() => {
                  close();
                  item.onSelect();
                }}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
