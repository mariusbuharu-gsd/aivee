import type { ReactNode } from 'react';
import './eyes.css';

function Eye({ x }: { x: number }) {
  return (
    <g transform={`translate(${x} 50)`}>
      <g className="lid">
        <circle className="ring" r="19" />
        <g className="p">
          {/* Invisible ring-sized circle: keeps the pupil's transform centred on the eye. */}
          <circle r="15" fill="none" />
          <circle className="pupil" r="8" />
        </g>
      </g>
    </g>
  );
}

/** The loader: the logo's eyes look around (left, right, up) and blink. Decorative only. */
export function LookingEyes({ size = 48 }: { size?: number }) {
  return (
    <svg
      className="eyes-look"
      width={size}
      height={Math.round((size * 49) / 91)}
      viewBox="4.5 25.5 91 49"
      aria-hidden="true"
      focusable="false"
    >
      <Eye x={29} />
      <Eye x={71} />
    </svg>
  );
}

/** "Eyes + what is loading", announced to screen readers. `page` fills the screen. */
export function Loading({
  children,
  size = 28,
  page = false,
}: {
  children: ReactNode;
  size?: number;
  page?: boolean;
}) {
  return (
    <p className={`loading${page ? ' loading-page' : ''}`} role="status">
      <LookingEyes size={page ? 96 : size} />
      <span>{children}</span>
    </p>
  );
}

/** Button content while busy: small eyes before the busy text, the idle text otherwise. */
export function BusyLabel({
  busy,
  idle,
  children,
}: {
  busy: boolean;
  idle: ReactNode;
  children: ReactNode;
}) {
  if (!busy) return <>{idle}</>;
  return (
    <>
      <LookingEyes size={20} />
      {children}
    </>
  );
}
