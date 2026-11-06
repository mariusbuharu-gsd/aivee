import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { useAuth } from '../auth/context';
import { isEmail, MIN_PASSWORD, passwordStrength, type VenueType } from '../auth/session';
import { AuthShell } from '../components/AuthShell';

const VENUES: { id: VenueType; label: string }[] = [
  { id: 'restaurant', label: 'Restaurant' },
  { id: 'bar', label: 'Terasă / bar' },
  { id: 'event', label: 'Eveniment' },
];

const STRENGTH = [
  '',
  'Prea scurtă.',
  'Parolă bună.',
  'Parolă puternică.',
  'Parolă foarte puternică.',
];

const STEPS = [
  ['Creezi contul și locația', 'Acum, pe pagina asta.'],
  ['Conectezi dispozitivul și camera', 'Un calculator din local, cu adresa camerei.'],
  ['Desenezi mesele și scrii prima regulă', 'În română, ca unui coleg.'],
];

export function RegisterPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [venue, setVenue] = useState('');
  const [venueType, setVenueType] = useState<VenueType>('restaurant');
  const [password, setPassword] = useState('');
  const [terms, setTerms] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const strength = passwordStrength(password);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError('Scrie-ți numele.');
    if (!isEmail(email)) return setError('Scrie o adresă de email validă.');
    if (!venue.trim()) return setError('Scrie numele locației.');
    if (password.length < MIN_PASSWORD)
      return setError(`Parola are nevoie de minim ${MIN_PASSWORD} caractere.`);
    if (!terms) return setError('Bifează acordul ca să continui.');
    signIn({ name: name.trim(), email: email.trim(), venue: venue.trim(), venueType }, true);
    navigate('/dispozitive', { replace: true });
  }

  return (
    <AuthShell
      aside={
        <>
          <h2 className="auth-claim">În 10 minute primești prima alertă.</h2>
          <ol className="auth-steps">
            {STEPS.map(([title, hint], i) => (
              <li key={title} aria-current={i === 0 ? 'step' : undefined}>
                <span className="auth-step-n">{i + 1}</span>
                <span>
                  <strong>{title}</strong>
                  <span className="auth-step-hint">{hint}</span>
                </span>
              </li>
            ))}
          </ol>
        </>
      }
    >
      <form className="auth-form auth-form-wide" onSubmit={submit} noValidate>
        <div className="auth-head">
          <span className="mono small muted">pasul 1 din 3</span>
          <h1>Cont nou</h1>
        </div>
        <div className="field-pair">
          <label className="field">
            <span>Numele tău</span>
            <input
              className="input"
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Email</span>
            <input
              className="input"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
        </div>
        <label className="field">
          <span>Numele locației</span>
          <input
            className="input"
            autoComplete="organization"
            value={venue}
            onChange={(e) => setVenue(e.target.value)}
            placeholder="ex. Bistro Central"
          />
        </label>
        <fieldset className="choices">
          <legend>Tip de locație</legend>
          {VENUES.map((v) => (
            <label key={v.id} className="choice">
              <input
                type="radio"
                name="venueType"
                checked={venueType === v.id}
                onChange={() => setVenueType(v.id)}
              />
              {v.label}
            </label>
          ))}
        </fieldset>
        <label className="field">
          <span>Parolă</span>
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-describedby="pw-hint"
          />
        </label>
        <div className="meter" aria-hidden="true">
          {[1, 2, 3, 4].map((n) => (
            <span key={n} className={n <= strength ? 'is-on' : undefined} />
          ))}
        </div>
        <span id="pw-hint" className="small muted">
          {STRENGTH[strength]} Minim {MIN_PASSWORD} caractere.
        </span>
        <label className="check">
          <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
          <span>
            Sunt de acord cu termenii și cu felul în care prelucrăm imaginile: fețele se blurează
            local, video-ul nu pleacă din restaurant.
          </span>
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="btn btn-primary btn-block">
          Creează contul și continuă
        </button>
        <p className="auth-switch">
          Ai deja cont? <Link to="/intra">Intră în cont</Link>
        </p>
      </form>
    </AuthShell>
  );
}
