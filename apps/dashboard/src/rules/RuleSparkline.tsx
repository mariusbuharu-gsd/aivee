import { alertsCount } from './count';

const BAR = 4;
const GAP = 3;
const HEIGHT = 18;

/**
 * How many alerts a rule raised per day, oldest first: one thin bar per day, no axes, plus the
 * total. Quiet on purpose: the rule's sentence stays the card's main line.
 */
export function RuleSparkline({ perDay }: { perDay: number[] }) {
  const total = perDay.reduce((a, b) => a + b, 0);
  const max = Math.max(1, ...perDay);
  const width = perDay.length * (BAR + GAP) - GAP;
  return (
    <span
      className="rule-spark"
      role="img"
      aria-label={`${alertsCount(total)} în ultimele ${perDay.length} zile`}
    >
      <svg
        viewBox={`0 0 ${width} ${HEIGHT}`}
        width={width * 1.5}
        height={HEIGHT}
        aria-hidden="true"
      >
        {perDay.map((n, i) => {
          const h = n === 0 ? 1 : Math.max(3, Math.round((n / max) * HEIGHT));
          return (
            <rect
              key={i}
              x={i * (BAR + GAP)}
              y={HEIGHT - h}
              width={BAR}
              height={h}
              rx={1}
              className={n === 0 ? 'is-zero' : undefined}
            />
          );
        })}
      </svg>
      <span className="rule-spark-total">{alertsCount(total)}</span>
      <span className="rule-spark-days">în {perDay.length} zile</span>
    </span>
  );
}
