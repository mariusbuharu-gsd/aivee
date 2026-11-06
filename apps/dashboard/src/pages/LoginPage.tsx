import { useRef, useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router';
import { useApi } from '../api/context';
import { MOCK_PASSWORD, MOCK_USERS } from '../api/mockAccounts';
import type { Role } from '../api/client';
import { useAuth } from '../auth/context';
import { isEmail, safeNext } from '../auth/session';
import { AuthScene, AuthShell } from '../components/AuthShell';
import { Banner } from '../ui/Banner';
import { PasswordInput } from '../ui/controls';
import { BusyLabel } from '../ui/Eyes';

/** The demo accounts as the roles they stand for; one click signs in. */
const DEMO_ROLES: Record<Role, { label: string; can: string }> = {
  owner: { label: 'Proprietar', can: 'vede tot, setează reguli' },
  manager: { label: 'Manager', can: 'reguli, camere, tură' },
  staff: { label: 'Ospătar', can: 'alertele și „Merg eu”' },
};
const roleOf = (email: string) => email.split('@')[0] as Role;

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
  const [forgot, setForgot] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);
  const sceneRef = useRef<HTMLDivElement>(null);

  if (status === 'authed') return <Navigate to={next} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (!isEmail(email)) return setError('Scrie o adresă de email validă.');
    if (!password) return setError('Scrie parola.');
    await signIn(email, password);
  }

  async function signIn(who: string, secret: string) {
    setBusy(true);
    setError(null);
    try {
      await login(who, secret);
      navigate(next, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nu am putut intra în cont.');
      passwordRef.current?.select();
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      watch={sceneRef}
      aside={
        <>
          <AuthScene ref={sceneRef} />
          <h2 className="auth-claim">Ochii în plus ai personalului tău.</h2>
          <p className="auth-lead">
            Video-ul e analizat și aruncat, în cloud-ul nostru din UE sau, la cerere, pe un
            calculator din locație. În cont vezi doar alertele, regulile și cadre cu fețele blurate.
          </p>
        </>
      }
    >
      <form className="auth-form" onSubmit={submit} noValidate>
        <div className="auth-head">
          <h1>Intră în cont</h1>
          <p className="muted">Bine ai revenit. Alertele de azi te așteaptă.</p>
        </div>
        {error && <Banner tone="error" title={error} />}
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
        <PasswordInput
          label="Parolă"
          ref={passwordRef}
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          <BusyLabel busy={busy} idle="Intră în cont">
            Se verifică…
          </BusyLabel>
        </button>
        <div className="auth-forgot">
          <button
            type="button"
            className="link-btn"
            aria-expanded={forgot}
            onClick={() => setForgot((v) => !v)}
          >
            Am uitat parola
          </button>
          {forgot && (
            <p className="small muted">
              Cere-i proprietarului contului un link de invitație nou pe același email; cu el îți
              alegi altă parolă.
            </p>
          )}
        </div>
        <p className="auth-switch">
          Nu ai cont? <Link to="/cont-nou">Creează unul</Link>
        </p>
        {api.kind === 'mock' && (
          <div className="auth-demo" role="group" aria-labelledby="demo-h">
            <p id="demo-h" className="small muted">
              Încearcă un cont demo (parola {MOCK_PASSWORD}):
            </p>
            <div className="auth-demo-roles">
              {MOCK_USERS.map((u) => {
                const r = DEMO_ROLES[roleOf(u)];
                return (
                  <button
                    key={u}
                    type="button"
                    className="auth-role"
                    disabled={busy}
                    onClick={() => {
                      setEmail(u);
                      setPassword(MOCK_PASSWORD);
                      void signIn(u, MOCK_PASSWORD);
                    }}
                  >
                    <strong>{r.label}</strong>
                    <small>{r.can}</small>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </form>
    </AuthShell>
  );
}
