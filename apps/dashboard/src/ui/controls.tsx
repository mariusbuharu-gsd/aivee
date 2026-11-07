import { useId, useState, type ComponentProps, type ReactNode } from 'react';
import { Icon, type IconName } from '../components/Icon';
import { LookingEyes } from './Eyes';

/** On/off for something that takes effect at once (a rule). */
export function Switch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className={`switch ${disabled ? 'is-disabled' : ''}`}>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="switch-track" aria-hidden="true" />
      <span className="switch-label">{label}</span>
    </label>
  );
}

export interface SegmentOption<V extends string> {
  value: V;
  label: string;
  /** CSS class for a small colour swatch (e.g. the zone colour). */
  swatch?: string;
  /** A small count after the label ("Deschise 1"); hidden when absent or zero. */
  count?: number;
}

/** Two to four mutually exclusive choices, all visible at once. */
export function Segmented<V extends string>({
  label,
  hideLabel = false,
  value,
  options,
  onChange,
}: {
  label: string;
  hideLabel?: boolean;
  value: V;
  options: SegmentOption<V>[];
  onChange: (value: V) => void;
}) {
  const id = useId();
  return (
    <div className="seg-field">
      <span id={id} className={hideLabel ? 'sr-only' : 'seg-label'}>
        {label}
      </span>
      <div className="segmented" role="group" aria-labelledby={id}>
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            className="btn btn-seg"
            aria-pressed={o.value === value}
            onClick={() => onChange(o.value)}
          >
            {o.swatch && <span className={`swatch ${o.swatch}`} aria-hidden="true" />}
            {o.label}
            {o.count ? (
              <>
                {' '}
                <span className="seg-count mono">{o.count}</span>
              </>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
}

/** What an empty list says, plus the one thing to do about it. */
export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon: IconName;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon" aria-hidden="true">
        <Icon name={icon} size={22} />
      </span>
      <strong>{title}</strong>
      {children && <p className="muted small">{children}</p>}
      {action}
    </div>
  );
}

/** Placeholder rows while data loads, in place of "Se încarcă…". */
export function Skeleton({ rows = 3, label = 'Se încarcă' }: { rows?: number; label?: string }) {
  return (
    <div className="skeleton" role="status" aria-label={label}>
      <p className="loading" aria-hidden="true">
        <LookingEyes size={28} />
        <span>{label}…</span>
      </p>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="sk-row">
          <span className="sk sk-avatar" />
          <span className="sk-lines">
            <span className="sk" style={{ width: `${40 + ((i * 17) % 30)}%` }} />
            <span className="sk" style={{ width: `${70 + ((i * 11) % 25)}%` }} />
          </span>
        </div>
      ))}
    </div>
  );
}

/** A password field with "Arată" / "Ascunde". */
export function PasswordInput({
  label,
  ...rest
}: { label: string } & Omit<ComponentProps<'input'>, 'type'>) {
  const [shown, setShown] = useState(false);
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={rest.id ?? id}>{label}</label>
      <div className="password">
        <input {...rest} id={rest.id ?? id} className="input" type={shown ? 'text' : 'password'} />
        <button
          type="button"
          className="btn btn-ghost btn-sm password-toggle"
          aria-pressed={shown}
          aria-label={shown ? 'Ascunde parola' : 'Arată parola'}
          onClick={() => setShown((v) => !v)}
        >
          {shown ? 'Ascunde' : 'Arată'}
        </button>
      </div>
    </div>
  );
}
