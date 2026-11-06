import type { ReactNode } from 'react';
import { Icon, type IconName } from '../components/Icon';

export type BannerTone = 'info' | 'ok' | 'warn' | 'error';

const ICON: Record<BannerTone, IconName> = {
  info: 'info',
  ok: 'checkCircle',
  warn: 'warn',
  error: 'errorCircle',
};

/**
 * The state of a page or a form: offline, no access, no live stream. Errors are announced at
 * once (`role="alert"`); the other tones politely.
 */
export function Banner({
  tone,
  title,
  children,
  action,
  className = '',
}: {
  tone: BannerTone;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`banner banner-${tone} ${className}`}
      role={tone === 'error' ? 'alert' : 'status'}
    >
      <Icon name={ICON[tone]} />
      <div className="banner-body">
        <strong>{title}</strong>
        {children && <span>{children}</span>}
      </div>
      {action && <div className="banner-action">{action}</div>}
    </div>
  );
}
