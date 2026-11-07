import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import type { InviteInfo } from '../api/client';
import { useApi } from '../api/context';
import { useAuth } from '../auth/context';
import { MIN_PASSWORD, passwordStrength, ROLE_LABEL } from '../auth/session';
import { AuthShell } from '../components/AuthShell';
import { Banner } from '../ui/Banner';
import { PasswordInput, Skeleton } from '../ui/controls';
import { PasswordMeter } from '../components/PasswordMeter';

export function InvitePage() {
  const { token = '' } = useParams();
  const api = useApi();
  const { acceptInvite } = useAuth();
  const navigate = useNavigate();
  const [info, setInfo] = useState<InviteInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.getInvite(token).then(
      (i) => alive && setInfo(i),
      (e: unknown) => alive && setLoadError(e instanceof Error ? e.message : String(e)),
    );
    return () => {
      alive = false;
    };
  }, [api, token]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (!name.trim()) return setError('Scrie-ți numele.');
    if (password.length < MIN_PASSWORD)
      return setError(`Parola are nevoie de minim ${MIN_PASSWORD} caractere.`);
    setBusy(true);
    setError(null);
    try {
      await acceptInvite(token, { name: name.trim(), password });
      navigate('/', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nu am putut accepta invitația.');
      setBusy(false);
    }
  }

  return (
    <AuthShell
      aside={
        <>
          <h2 className="auth-claim">Echipa ta te așteaptă.</h2>
          <p className="auth-lead">
            Primești alertele locației pe telefon și apeși „Preiau” când pleci spre masă.
          </p>
        </>
      }
    >
      {loadError ? (
        <div className="auth-form">
          <h1>Invitație</h1>
          <Banner tone="error" title={loadError}>
            Cere-i managerului un link nou.
          </Banner>
          <Link to="/intra" className="btn btn-block">
            Intră în cont
          </Link>
        </div>
      ) : !info ? (
        <Skeleton rows={2} label="Se verifică invitația" />
      ) : (
        <form className="auth-form" onSubmit={submit} noValidate>
          <div className="auth-head">
            <span className="mono small muted">invitație · {info.org_name}</span>
            <h1>Intră în echipa {info.location_name}</h1>
            <p className="muted">
              Rol: <strong>{ROLE_LABEL[info.role]}</strong> · cont pentru {info.email}
            </p>
          </div>
          <label className="field">
            <span>Numele tău</span>
            <input
              className="input"
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <PasswordInput
            label="Parolă"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-describedby="inv-pw"
          />
          <PasswordMeter id="inv-pw" strength={passwordStrength(password)} />
          {error && <Banner tone="error" title={error} />}
          <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
            Acceptă invitația
          </button>
        </form>
      )}
    </AuthShell>
  );
}
