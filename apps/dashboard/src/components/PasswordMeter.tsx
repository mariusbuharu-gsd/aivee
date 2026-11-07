import { MIN_PASSWORD } from '../auth/session';

const STRENGTH = [
  '',
  'Prea scurtă.',
  'Parolă bună.',
  'Parolă puternică.',
  'Parolă foarte puternică.',
];

export function PasswordMeter({ id, strength }: { id: string; strength: 0 | 1 | 2 | 3 | 4 }) {
  return (
    <>
      <div className="meter" aria-hidden="true">
        {[1, 2, 3, 4].map((n) => (
          <span key={n} className={n <= strength ? 'is-on' : undefined} />
        ))}
      </div>
      <span id={id} className="small muted">
        {STRENGTH[strength]} Minim {MIN_PASSWORD} caractere.
      </span>
    </>
  );
}
