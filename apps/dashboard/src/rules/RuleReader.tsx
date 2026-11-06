import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { CHIP_KEYS, type ChipKey, type Phrase, type RuleChip } from './chips';

// The logo eyes read the request, the same moment as on the presentation site
// (apps/site/src/rules.js): they stop on each understood phrase, it gets underlined and its chip
// drops in; chips without a phrase drop at the end, the dark "Atunci" last. It plays again every
// time the reader comes back into view. Without IntersectionObserver or with reduced motion the
// finished state shows and nothing moves.

const CENTRES = [29, 71]; // ring centres in viewBox units, cy = 50
const MAX = 7.5; // inner ring radius 15.5 minus pupil 8: the pupil never touches the ring

type Step = { phrase?: number; chip?: ChipKey };

function stepsFor(phrases: Phrase[]): Step[] {
  const dropped = new Set<ChipKey>();
  const steps: Step[] = phrases.map((p, i) => {
    const fresh = p.chip !== 'then' && !dropped.has(p.chip);
    if (fresh) dropped.add(p.chip);
    return { phrase: i, chip: fresh ? p.chip : undefined };
  });
  for (const key of CHIP_KEYS) if (key !== 'then' && !dropped.has(key)) steps.push({ chip: key });
  steps.push({ chip: 'then' });
  return steps;
}

function canMove(): boolean {
  if (typeof window === 'undefined' || typeof IntersectionObserver === 'undefined') return false;
  return !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

export function RuleReader({
  text,
  phrases,
  chips,
  open,
  onPick,
  editorId,
}: {
  text: string;
  phrases: Phrase[];
  chips: RuleChip[];
  open: ChipKey | null;
  onPick: (key: ChipKey) => void;
  /** Id of the per-chip editor, for `aria-controls`. */
  editorId: string;
}) {
  const steps = useMemo(() => stepsFor(phrases), [phrases]);
  const [moving] = useState(canMove);
  const [done, setDone] = useState(moving ? 0 : steps.length);
  const root = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const textEl = useRef<HTMLParagraphElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const keys = useRef<(HTMLSpanElement | null)[]>([]);

  useEffect(() => {
    if (!moving || !root.current) return;
    let run = 0;
    let playing = false;
    const timers = new Set<ReturnType<typeof setTimeout>>();
    const wait = (ms: number) =>
      new Promise<void>((ok) => {
        const t = setTimeout(() => {
          timers.delete(t);
          ok();
        }, ms);
        timers.add(t);
      });
    const pupils = () => [...(svg.current?.querySelectorAll<SVGCircleElement>('.pupil') ?? [])];

    function look(el: Element | null) {
      if (!el || !svg.current) return;
      const r = el.getBoundingClientRect();
      const x = r.left + r.width / 2;
      const y = r.top + r.height / 2;
      const box = svg.current.getBoundingClientRect();
      const vb = svg.current.viewBox.baseVal;
      const k = box.width / vb.width || 1;
      pupils().forEach((pupil, i) => {
        const dx = (x - (box.left + ((CENTRES[i] ?? 50) - vb.x) * k)) / k;
        const dy = (y - (box.top + (50 - vb.y) * k)) / k;
        const d = Math.hypot(dx, dy) || 1;
        const m = Math.min(d * 0.35, MAX);
        pupil.style.transform = `translate(${(dx / d) * m}px, ${(dy / d) * m}px)`;
      });
    }

    function rewind() {
      run++;
      setDone(0);
      for (const p of pupils()) p.style.transform = '';
    }

    async function read() {
      const id = ++run;
      const live = () => id === run;
      look(textEl.current);
      await wait(450);
      for (const [i, s] of steps.entries()) {
        if (!live()) return;
        if (s.phrase !== undefined) {
          look(keys.current[s.phrase] ?? null);
          await wait(400);
        } else {
          look(list.current?.querySelector(`[data-chip="${s.chip}"]`) ?? null);
          await wait(260);
        }
        if (!live()) return;
        setDone(i + 1);
        await wait(s.phrase !== undefined ? 460 : 220);
      }
      if (live()) look(list.current);
    }

    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        if (entry.intersectionRatio >= 0.5 && !playing) {
          playing = true;
          void read();
        } else if (!entry.isIntersecting && playing) {
          playing = false;
          rewind();
        }
      },
      { threshold: [0, 0.5] },
    );
    io.observe(root.current);
    return () => {
      run++;
      io.disconnect();
      timers.forEach(clearTimeout);
    };
  }, [moving, steps]);

  const read = steps.slice(0, done);
  const hit = new Set(read.flatMap((s) => (s.phrase === undefined ? [] : [s.phrase])));
  const shown = new Set(read.flatMap((s) => (s.chip ? [s.chip] : [])));

  const parts: ReactNode[] = [];
  let at = 0;
  phrases.forEach((p, i) => {
    if (p.start > at) parts.push(text.slice(at, p.start));
    parts.push(
      <span
        key={i}
        ref={(el) => {
          keys.current[i] = el;
        }}
        className={`reader-k ${hit.has(i) ? 'is-hit' : ''}`}
      >
        {text.slice(p.start, p.end)}
      </span>,
    );
    at = p.end;
  });
  if (at < text.length) parts.push(text.slice(at));

  return (
    <div className="reader" ref={root}>
      <div className="reader-line">
        <svg
          ref={svg}
          className="reader-eyes"
          viewBox="4.5 25.5 91 49"
          aria-hidden="true"
          focusable="false"
        >
          <circle className="ring" cx="29" cy="50" r="19" />
          <circle className="pupil" cx="29" cy="50" r="8" />
          <circle className="ring" cx="71" cy="50" r="19" />
          <circle className="pupil" cx="71" cy="50" r="8" />
        </svg>
        <p className="reader-text" ref={textEl} data-testid="rule-text">
          {phrases.length ? parts : text}
        </p>
      </div>
      <ul className="reader-chips" ref={list} aria-label="Părțile regulii">
        {chips.map((c) => (
          <li key={c.key}>
            <button
              type="button"
              data-chip={c.key}
              className={`reader-chip ${c.key === 'then' ? 'is-then' : ''} ${
                shown.has(c.key) ? '' : 'is-wait'
              } ${open === c.key ? 'is-open' : ''}`}
              aria-expanded={open === c.key}
              aria-controls={open === c.key ? editorId : undefined}
              onClick={() => onPick(c.key)}
            >
              <small>{c.label}</small>
              <span>{c.value}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
