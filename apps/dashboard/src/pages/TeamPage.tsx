import { useCallback, useEffect, useState, type FormEvent } from 'react';
import type { Invite, Member, Role } from '../api/client';
import { useApi } from '../api/context';
import { useAuth, useLocationId } from '../auth/context';
import { isEmail, ROLE_LABEL } from '../auth/session';

export function TeamPage() {
  const api = useApi();
  const locationId = useLocationId();
  const { me, location } = useAuth();
  const isOwner = location?.role === 'owner';
  const [members, setMembers] = useState<Member[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      api
        .listMembers(locationId)
        .then(setMembers, (e: unknown) => setError(e instanceof Error ? e.message : String(e))),
    [api, locationId],
  );
  useEffect(() => {
    void load();
  }, [load]);

  /** Managers manage staff only; nobody edits themselves here. */
  const editable = (m: Member) => m.user_id !== me?.user.id && (isOwner || m.role === 'staff');

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <h1>Echipă</h1>
        <p className="muted">Cine primește alertele din {location?.name} și ce poate face.</p>
      </header>
      <div className="two-col">
        <section aria-labelledby="members-h">
          <h2 id="members-h">Membri</h2>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {members.length === 0 ? (
            <p className="muted empty">Încă nu e nimeni în echipă. Trimite o invitație.</p>
          ) : (
            <ul className="members">
              {members.map((m) => (
                <li key={m.user_id} className="member">
                  <span className="audit-actor is-user" aria-hidden="true">
                    {m.name
                      .split(/\s+/)
                      .slice(0, 2)
                      .map((p) => p[0]?.toUpperCase())
                      .join('')}
                  </span>
                  <div className="member-who">
                    <strong>{m.name}</strong>
                    <span className="small muted">{m.email}</span>
                  </div>
                  {editable(m) ? (
                    <>
                      <label className="sr-only" htmlFor={`role-${m.user_id}`}>
                        Rol pentru {m.name}
                      </label>
                      <select
                        id={`role-${m.user_id}`}
                        className="input input-sm"
                        value={m.role}
                        disabled={!isOwner}
                        onChange={(e) =>
                          run(() => api.updateMember(locationId, m.user_id, e.target.value as Role))
                        }
                      >
                        <option value="manager">{ROLE_LABEL.manager}</option>
                        <option value="staff">{ROLE_LABEL.staff}</option>
                      </select>
                      <RemoveButton
                        name={m.name}
                        onConfirm={() => run(() => api.removeMember(locationId, m.user_id))}
                      />
                    </>
                  ) : (
                    <span className="pill pill-muted">{ROLE_LABEL[m.role]}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
        <aside className="side-col">
          <InviteForm locationId={locationId} canInviteManager={isOwner} onInvited={load} />
          <div className="card">
            <h2 className="h3">Ce poate face fiecare rol</h2>
            <dl className="roles">
              <dt>{ROLE_LABEL.manager}</dt>
              <dd>
                Reguli, camere, zone, confirmarea personalului, echipa (doar personal) și istoricul.
              </dd>
              <dt>{ROLE_LABEL.staff}</dt>
              <dd>Alerte pe telefon, „Merg eu” și istoricul propriu.</dd>
            </dl>
          </div>
        </aside>
      </div>
    </div>
  );
}

/** A two-step remove: the first click asks, the second removes. */
function RemoveButton({ name, onConfirm }: { name: string; onConfirm: () => void }) {
  const [asking, setAsking] = useState(false);
  return asking ? (
    <span className="confirm">
      <button type="button" className="btn btn-danger btn-sm" onClick={onConfirm}>
        Scoate
      </button>
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAsking(false)}>
        Anulează
      </button>
    </span>
  ) : (
    <button
      type="button"
      className="btn btn-ghost btn-sm"
      aria-label={`Scoate-l pe ${name} din echipă`}
      onClick={() => setAsking(true)}
    >
      Scoate
    </button>
  );
}

function InviteForm({
  locationId,
  canInviteManager,
  onInvited,
}: {
  locationId: string;
  canInviteManager: boolean;
  onInvited: () => void;
}) {
  const api = useApi();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>('staff');
  const [invite, setInvite] = useState<Invite | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!isEmail(email)) return setError('Scrie o adresă de email validă.');
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      setInvite(await api.createInvite({ location_id: locationId, role, email: email.trim() }));
      onInvited();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!invite) return;
    try {
      await navigator.clipboard.writeText(invite.invite_url);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <form className="card invite" onSubmit={submit} noValidate aria-labelledby="invite-h">
      <h2 id="invite-h" className="h3">
        Invită pe cineva
      </h2>
      <label className="field">
        <span>Email</span>
        <input
          id="invite-email"
          className="input"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="ospatar@restaurant.ro"
        />
      </label>
      <fieldset className="choices">
        <legend>Rol</legend>
        <label className="choice">
          <input
            type="radio"
            name="invite-role"
            checked={role === 'staff'}
            onChange={() => setRole('staff')}
          />
          {ROLE_LABEL.staff}
        </label>
        {canInviteManager && (
          <label className="choice">
            <input
              type="radio"
              name="invite-role"
              checked={role === 'manager'}
              onChange={() => setRole('manager')}
            />
            {ROLE_LABEL.manager}
          </label>
        )}
      </fieldset>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="btn btn-primary" disabled={busy}>
        Creează linkul de invitație
      </button>
      {invite && (
        <div className="invite-link" role="status">
          <span className="small muted">
            Trimite linkul pe WhatsApp sau email. Expiră pe{' '}
            {new Date(invite.expires_at).toLocaleDateString('ro-RO', {
              day: 'numeric',
              month: 'long',
            })}
            .
          </span>
          <div className="invite-copy">
            <input
              className="input mono"
              readOnly
              value={invite.invite_url}
              aria-label="Link de invitație"
              onFocus={(e) => e.target.select()}
            />
            <button type="button" className="btn" onClick={copy}>
              {copied ? 'Copiat' : 'Copiază'}
            </button>
          </div>
        </div>
      )}
    </form>
  );
}
