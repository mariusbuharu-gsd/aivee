import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';
import { Logo } from './Icon';
import './AuthShell.css';

/** Two-panel frame for the sign-in pages: a night story panel and the form on light ground. */
export function AuthShell({
  aside,
  children,
  watch,
}: {
  aside: ReactNode;
  children: ReactNode;
  /** When given, the logo's eyes look at this element (the live scene on Intră în cont). */
  watch?: RefObject<HTMLElement | null>;
}) {
  return (
    <div className="auth">
      <section className="auth-side on-night" aria-label="Despre AiVee">
        {watch ? <WatchingLogo target={watch} /> : <Logo />}
        <div className="auth-story">{aside}</div>
      </section>
      <main id="main" className="auth-main">
        {children}
      </main>
    </div>
  );
}

/** Eye centres and the viewBox of the brand mark (docs/brand/aivee-mark-white.svg). */
const EYES = [29, 71] as const;
const VB = { x: 4.5, y: 25.5, w: 91 };
/** How far a pupil travels from the centre, in viewBox units; the mark's resting look. */
const REACH = 5;
const REST = { dx: 3.6, dy: 1.8 };

/** The logo with pupils that turn toward `target`; resting look when it is hidden or absent. */
function WatchingLogo({ target }: { target: RefObject<HTMLElement | null> }) {
  const svg = useRef<SVGSVGElement>(null);
  const [look, setLook] = useState<{ dx: number; dy: number }[]>([REST, REST]);

  useLayoutEffect(() => {
    const aim = () => {
      const s = svg.current?.getBoundingClientRect();
      const t = target.current?.getBoundingClientRect();
      if (!s || !t || !s.width || !t.width) return setLook([REST, REST]);
      const k = s.width / VB.w;
      const tx = t.left + t.width / 2;
      const ty = t.top + t.height / 2;
      setLook(
        EYES.map((cx) => {
          const dx = tx - (s.left + (cx - VB.x) * k);
          const dy = ty - (s.top + (50 - VB.y) * k);
          const d = Math.hypot(dx, dy) || 1;
          return { dx: (dx / d) * REACH, dy: (dy / d) * REACH };
        }),
      );
    };
    aim();
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(aim);
    if (ro && target.current) ro.observe(target.current);
    window.addEventListener('resize', aim);
    return () => {
      ro?.disconnect();
      window.removeEventListener('resize', aim);
    };
  }, [target]);

  return (
    <span className="logo">
      <svg
        ref={svg}
        width="40"
        height="22"
        viewBox={`${VB.x} ${VB.y} ${VB.w} 49`}
        aria-hidden="true"
        focusable="false"
      >
        {EYES.map((cx, i) => (
          <g key={cx}>
            <circle cx={cx} cy="50" r="19" fill="none" stroke="currentColor" strokeWidth="7" />
            <circle
              className="auth-pupil"
              cx={cx}
              cy="50"
              r="8"
              fill="var(--coral)"
              style={{ transform: `translate(${look[i]?.dx ?? 0}px, ${look[i]?.dy ?? 0}px)` }}
            />
          </g>
        ))}
      </svg>
      <span className="logo-word">aivee</span>
    </span>
  );
}

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

/**
 * A small camera frame: guests at table 4 and the wait timer running. Decorative; with
 * prefers-reduced-motion the timer stands still.
 */
export function AuthScene({ ref }: { ref?: RefObject<HTMLDivElement | null> }) {
  const [wait, setWait] = useState(356);
  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
    const t = window.setInterval(() => setWait((s) => (s >= 420 ? 330 : s + 1)), 1000);
    return () => window.clearInterval(t);
  }, []);

  return (
    <figure className="auth-scene" aria-hidden="true">
      <div className="auth-cam" ref={ref}>
        <span className="auth-cam-live mono">● cam-sala</span>
        <span className="auth-cam-wall" />
        <span className="auth-cam-table" />
        <span className="auth-cam-zone" />
        <span className="auth-cam-guest" style={{ left: '58%', top: '34%' }} />
        <span className="auth-cam-guest" style={{ left: '73%', top: '37%' }} />
        <span className="auth-cam-label mono">
          MASA 4 · <span className="auth-cam-timer">{fmt(wait)}</span>
        </span>
      </div>
      <figcaption className="auth-alert-meta mono">
        2 clienți · niciun ospătar · alertă trimisă
      </figcaption>
    </figure>
  );
}
