import { useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router';
import { useApi } from '../api/context';
import { MOCK_PASSWORD, MOCK_USERS } from '../api/mockAccounts';
import { useAuth } from '../auth/context';
import { isEmail, safeNext } from '../auth/session';
import { AuthShell } from '../components/AuthShell';

export function LoginPage() {
  const api = useApi();
  const { login, status } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === 'authed') return <Navigate to={next} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (!isEmail(email)) return setError('Scrie o adresă de email validă.');
    if (!password) return setError('Scrie parola.');
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate(next, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nu am putut intra în cont.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      aside={
        <>
          <div className="auth-alert" aria-hidden="true">
            <span className="pill pill-alert">deschisă</span>
            <p className="auth-alert-title">Masa 4 așteaptă de 6 min</p>
            <p className="auth-alert-meta mono">cam-sala · 2 clienți · niciun ospătar</p>
          </div>
          <h2 className="auth-claim">Ochii în plus ai personalului tău.</h2>
          <p className="auth-lead">
            Video-ul rămâne în locație. În cont vezi doar alertele, regulile și cadre cu fețele
            blurate.
          </p>
        </>
      }
    >
      <form className="auth-form" onSubmit={submit} noValidate>
        <div className="auth-head">
          <h1>Intră în cont</h1>
          <p className="muted">Bine ai revenit. Alertele de azi te așteaptă.</p>
        </div>
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
        <label className="field">
          <span>Parolă</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? 'Se verifică…' : 'Intră în cont'}
        </button>
        <p className="auth-switch">
          Nu ai cont? <Link to="/cont-nou">Creează unul</Link>
        </p>
        {api.kind === 'mock' && (
          <div className="auth-demo">
            <p className="small muted">Conturi demo (parola {MOCK_PASSWORD}):</p>
            <div className="auth-demo-users">
              {MOCK_USERS.map((u) => (
                <button
                  key={u}
                  type="button"
                  className="btn btn-sm"
                  onClick={() => {
                    setEmail(u);
                    setPassword(MOCK_PASSWORD);
                  }}
                >
                  {u.split('@')[0]}
                </button>
              ))}
            </div>
          </div>
        )}
      </form>
    </AuthShell>
  );
}
