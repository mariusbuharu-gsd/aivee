import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { useAuth } from '../auth/context';
import { isEmail } from '../auth/session';
import { AuthShell } from '../components/AuthShell';

/** Only same-app paths are followed after sign-in. */
function safeNext(next: string | null) {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/';
}

const nameFromEmail = (email: string) => email.split('@')[0] ?? email;

export function LoginPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!isEmail(email)) return setError('Scrie o adresă de email validă.');
    if (!password) return setError('Scrie parola.');
    signIn(
      {
        name: nameFromEmail(email.trim()),
        email: email.trim(),
        venue: '',
        venueType: 'restaurant',
      },
      remember,
    );
    navigate(safeNext(params.get('next')), { replace: true });
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
            Video-ul rămâne în restaurant. În cont vezi doar alertele, regulile și cadre cu fețele
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
        <label className="check">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
          />
          Ține-mă minte pe acest dispozitiv
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="btn btn-primary btn-block">
          Intră în cont
        </button>
        <p className="auth-switch">
          Nu ai cont? <Link to="/cont-nou">Creează unul</Link>
        </p>
        <p className="auth-note mono small">Demo: contul se păstrează doar în acest browser.</p>
      </form>
    </AuthShell>
  );
}
