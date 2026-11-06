import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { Icon } from '../components/Icon';

export interface SelectOption<V extends string = string> {
  value: V;
  label: string;
  /** A short line under or beside the label ("reguli, camere, echipă"). */
  hint?: string;
  /** Shown before the label, e.g. an avatar. */
  leading?: ReactNode;
}

/**
 * Our replacement for the native `<select>`: a select-only combobox (WAI-ARIA APG) with
 * keyboard support (arrows, Home/End, Enter, Esc, type-ahead) and an optional search field.
 */
export function Select<V extends string>({
  label,
  hideLabel = false,
  value,
  options,
  onChange,
  searchable = false,
  searchPlaceholder = 'Caută',
  emptyText = 'Nimic găsit.',
  disabled = false,
  size,
  icon,
  className = '',
  id,
}: {
  label: string;
  hideLabel?: boolean;
  value: V;
  options: SelectOption<V>[];
  onChange: (value: V) => void;
  searchable?: boolean;
  searchPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  size?: 'sm';
  /** Leading icon inside the button. */
  icon?: ReactNode;
  className?: string;
  id?: string;
}) {
  const auto = useId();
  const base = id ?? auto;
  const labelId = `${base}-label`;
  const listId = `${base}-list`;
  const optId = (i: number) => `${base}-opt-${i}`;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const typed = useRef({ text: '', at: 0 });

  const q = query.trim().toLocaleLowerCase('ro-RO');
  const shown = q
    ? options.filter((o) => `${o.label} ${o.hint ?? ''}`.toLocaleLowerCase('ro-RO').includes(q))
    : options;
  const current = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (root.current?.contains(e.target as Node)) return;
      setOpen(false);
      setQuery('');
    };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (searchable) search.current?.focus();
    document.getElementById(optId(active))?.scrollIntoView?.({ block: 'nearest' });
  });

  function show() {
    if (disabled) return;
    setQuery('');
    setActive(
      Math.max(
        0,
        options.findIndex((o) => o.value === value),
      ),
    );
    setOpen(true);
  }

  function close(focus = true) {
    setOpen(false);
    setQuery('');
    if (focus) button.current?.focus();
  }

  function choose(o: SelectOption<V> | undefined) {
    if (!o) return;
    close();
    if (o.value !== value) onChange(o.value);
  }

  function onKey(e: KeyboardEvent) {
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
        e.preventDefault();
        show();
      }
      return;
    }
    const last = shown.length - 1;
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setActive((i) => Math.min(last, i + 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setActive((i) => Math.max(0, i - 1));
        break;
      case 'Home':
        e.preventDefault();
        setActive(0);
        break;
      case 'End':
        e.preventDefault();
        setActive(last);
        break;
      case 'Enter':
        e.preventDefault();
        choose(shown[active]);
        break;
      case ' ':
        if (searchable) return;
        e.preventDefault();
        choose(shown[active]);
        break;
      case 'Escape':
        e.preventDefault();
        close();
        break;
      case 'Tab':
        close(false);
        break;
      default:
        if (!searchable && e.key.length === 1) {
          const now = Date.now();
          const t = now - typed.current.at < 600 ? typed.current.text + e.key : e.key;
          typed.current = { text: t, at: now };
          const i = shown.findIndex((o) =>
            o.label.toLocaleLowerCase('ro-RO').startsWith(t.toLocaleLowerCase('ro-RO')),
          );
          if (i >= 0) setActive(i);
        }
    }
  }

  const activeId = open && shown[active] ? optId(active) : undefined;

  return (
    <div
      ref={root}
      className={`select ${size === 'sm' ? 'select-sm' : ''} ${className}`}
      data-open={open || undefined}
    >
      <span id={labelId} className={hideLabel ? 'sr-only' : 'select-label'}>
        {label}
      </span>
      <button
        ref={button}
        id={base}
        type="button"
        role="combobox"
        className="select-btn"
        aria-labelledby={labelId}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={searchable ? undefined : activeId}
        disabled={disabled}
        onClick={() => (open ? close() : show())}
        onKeyDown={searchable && open ? undefined : onKey}
      >
        {icon}
        <span className="select-value">
          {current?.leading}
          <span className="select-text">{current?.label ?? '—'}</span>
        </span>
        <Icon name="chevron" size={18} />
      </button>
      {open && (
        <div className="select-pop">
          {searchable && (
            <div className="select-search">
              <input
                ref={search}
                className="input"
                type="search"
                role="combobox"
                aria-label={`${searchPlaceholder} în ${label}`}
                aria-controls={listId}
                aria-expanded
                aria-autocomplete="list"
                aria-activedescendant={activeId}
                placeholder={searchPlaceholder}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setActive(0);
                }}
                onKeyDown={onKey}
              />
            </div>
          )}
          <ul id={listId} role="listbox" aria-labelledby={labelId} className="select-list">
            {shown.map((o, i) => (
              <li
                key={o.value}
                id={optId(i)}
                role="option"
                aria-selected={o.value === value}
                className={`select-opt ${i === active ? 'is-active' : ''}`}
                onPointerMove={() => setActive(i)}
                onClick={() => choose(o)}
              >
                {o.leading}
                <span className="select-opt-text">
                  <span>{o.label}</span>
                  {o.hint && <span className="select-hint">{o.hint}</span>}
                </span>
                {o.value === value && <Icon name="check" size={16} />}
              </li>
            ))}
          </ul>
          {shown.length === 0 && <p className="select-empty">{emptyText}</p>}
        </div>
      )}
    </div>
  );
}
