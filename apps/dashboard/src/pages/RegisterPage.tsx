import { useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate } from 'react-router';
import { useAuth } from '../auth/context';
import { isEmail, MIN_PASSWORD, passwordStrength } from '../auth/session';
import { AuthShell } from '../components/AuthShell';
import { PasswordMeter } from '../components/PasswordMeter';

const STEPS = [
  ['Creezi contul firmei', 'Acum, pe pagina asta. Tu devii proprietarul.'],
  ['Adaugi locația și camera', 'Restaurant, terasă, eveniment sau magazin.'],
  ['Desenezi zonele și scrii prima regulă', 'În română, ca unui coleg.'],
];

export function RegisterPage() {
  const { register, status } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [org, setOrg] = useState('');
  const [password, setPassword] = useState('');
  const [terms, setTerms] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === 'authed' && !busy) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (!name.trim()) return setError('Scrie-ți numele.');
    if (!isEmail(email)) return setError('Scrie o adresă de email validă.');
    if (!org.trim()) return setError('Scrie numele firmei.');
    if (password.length < MIN_PASSWORD)
      return setError(`Parola are nevoie de minim ${MIN_PASSWORD} caractere.`);
    if (!terms) return setError('Bifează acordul ca să continui.');
    setBusy(true);
    setError(null);
    try {
      await register({ org_name: org.trim(), name: name.trim(), email: email.trim(), password });
      navigate('/locatii', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nu am putut crea contul.');
      setBusy(false);
    }
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
          <span>Numele firmei</span>
          <input
            className="input"
            autoComplete="organization"
            value={org}
            onChange={(e) => setOrg(e.target.value)}
            placeholder="ex. Bistro Central SRL"
          />
        </label>
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
        <PasswordMeter id="pw-hint" strength={passwordStrength(password)} />
        <label className="check">
          <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
          <span>
            Sunt de acord cu termenii și cu felul în care prelucrăm imaginile: fețele se blurează
            local, video-ul nu pleacă din locație.
          </span>
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          Creează contul și continuă
        </button>
        <p className="auth-switch">
          Ai deja cont? <Link to="/intra">Intră în cont</Link>
        </p>
      </form>
    </AuthShell>
  );
}
