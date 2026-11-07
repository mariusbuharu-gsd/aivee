import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import type { Invite, Member, PendingInvite, Role } from '../api/client';
import { useApi } from '../api/context';
import { useAuth, useLocationId } from '../auth/context';
import { isEmail, ROLE_LABEL } from '../auth/session';
import { Banner } from '../ui/Banner';
import { ConfirmDialog } from '../ui/Dialog';
import { QrCode } from '../components/QrCode';
import { Menu, type MenuItem } from '../ui/Menu';
import { EmptyState, Segmented } from '../ui/controls';
import { useToast } from '../ui/toast';
import './TeamPage.css';

const initials = (name: string) =>
  name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('');

const day = (iso: string) =>
  new Date(iso).toLocaleDateString('ro-RO', { day: 'numeric', month: 'long' });

/** Copy a link and say so; the clipboard can refuse (no focus, no permission). */
async function copyLink(toast: ReturnType<typeof useToast>, url: string, text: string) {
  try {
    await navigator.clipboard.writeText(url);
    toast({ title: 'Link copiat', text });
  } catch {
    toast({
      kind: 'error',
      title: 'Nu am putut copia linkul',
      text: 'Selectează-l și copiază-l de mână.',
    });
  }
}

export function TeamPage() {
  const api = useApi();
  const toast = useToast();
  const navigate = useNavigate();
  const locationId = useLocationId();
  const { me, location } = useAuth();
  const isOwner = location?.role === 'owner';
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<PendingInvite[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Member | null>(null);
  const [revoking, setRevoking] = useState<PendingInvite | null>(null);
  /**
   * Links created in this tab, by email. The API stores only a hash of the token, so an older
   * invite's link cannot be read back; "Copiază link" re-issues it instead.
   */
  const [links, setLinks] = useState<Record<string, string>>({});

  const load = useCallback(
    () =>
      Promise.all([
        api.listMembers(locationId).then(setMembers),
        api.listInvites(locationId).then(setInvites, () => setInvites([])),
      ]).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e))),
    [api, locationId],
  );
  useEffect(() => {
    void load();
  }, [load]);
  /** The chat title, `true` for a group without a known title, null when none is linked. */
  const [telegram, setTelegram] = useState<string | true | null>(null);
  useEffect(() => {
    let live = true;
    api.getTelegramStatus(locationId).then(
      (t) => live && setTelegram(t.connected ? t.chat_title || true : null),
      () => live && setTelegram(null),
    );
    return () => {
      live = false;
    };
  }, [api, locationId]);

  /** Managers manage staff only; nobody edits themselves here. */
  const editable = (m: Member) =>
    m.role !== 'owner' && m.user_id !== me?.user.id && (isOwner || m.role === 'staff');

  async function copyInvite(i: PendingInvite) {
    const known = links[i.email];
    if (known) return copyLink(toast, known, `Expiră pe ${day(i.expires_at)}.`);
    setError(null);
    try {
      const fresh = await api.createInvite({
        location_id: locationId,
        role: i.role,
        email: i.email,
      });
      await api.revokeInvite(i.id);
      setLinks((l) => ({ ...l, [i.email]: fresh.invite_url }));
      await load();
      await copyLink(
        toast,
        fresh.invite_url,
        `Am făcut un link nou; cel trimis înainte nu mai merge. Expiră pe ${day(fresh.expires_at)}.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  /** Role changes live in the ⋯ menu, so a row is never re-roled by a stray tap. */
  function memberItems(m: Member): MenuItem[] {
    const other: Exclude<Role, 'owner'> = m.role === 'manager' ? 'staff' : 'manager';
    return [
      ...(isOwner
        ? [
            {
              label: `Schimbă rolul în ${ROLE_LABEL[other].toLowerCase()}`,
              onSelect: () => void setRole(m, other),
            },
          ]
        : []),
      {
        label: 'Vezi ce a făcut în Istoric',
        onSelect: () => navigate(`/istoric?cine=${encodeURIComponent(m.user_id)}`),
      },
      { label: 'Scoate din echipă…', danger: true, onSelect: () => setRemoving(m) },
    ];
  }

  async function setRole(m: Member, role: Role, undo = true) {
    setError(null);
    try {
      await api.updateMember(locationId, m.user_id, role);
      await load();
      toast({
        title: `${m.name} e acum ${ROLE_LABEL[role]}`,
        text:
          role === 'manager'
            ? 'Poate schimba reguli, camere și echipa.'
            : 'Primește alertele și poate apăsa „Preiau”.',
        action: undo ? { label: 'Anulează', run: () => setRole(m, m.role, false) } : undefined,
      });
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
          {telegram && (
            <p className="small muted team-telegram">
              Alertele merg și în grupul Telegram
              {telegram === true ? ' al locației' : ` „${telegram}”`}, pentru cine e în el.
            </p>
          )}
          {error && <Banner tone="error" title={error} />}
          {members.length === 0 ? (
            <EmptyState icon="team" title="Încă nu e nimeni în echipă">
              Trimite o invitație din dreapta; omul primește un link și își face singur contul.
            </EmptyState>
          ) : (
            <ul className="members">
              {members.map((m) => (
                <li key={m.user_id} className="member">
                  <span className="audit-actor is-user" aria-hidden="true">
                    {initials(m.name)}
                  </span>
                  <div className="member-who">
                    <strong>{m.name}</strong>
                    <span className="small muted">{m.email}</span>
                    {m.push_enabled !== undefined && (
                      <span className={`small member-push ${m.push_enabled ? 'is-on' : ''}`}>
                        {m.push_enabled ? 'notificări pornite' : 'fără notificări pe telefon'}
                      </span>
                    )}
                  </div>
                  <span className="team-role">{ROLE_LABEL[m.role]}</span>
                  {editable(m) ? (
                    <Menu label={`Acțiuni pentru ${m.name}`} items={memberItems(m)} />
                  ) : (
                    <span className="menu-spacer" aria-hidden="true" />
                  )}
                </li>
              ))}
            </ul>
          )}
          {invites.length > 0 && (
            <>
              <h2 id="invites-h">În așteptare</h2>
              <ul className="members" aria-labelledby="invites-h">
                {invites.map((i) => (
                  <li key={i.id} className="member is-pending">
                    <span className="audit-actor" aria-hidden="true">
                      @
                    </span>
                    <div className="member-who">
                      <strong>{i.email}</strong>
                      <span className="small muted">
                        {ROLE_LABEL[i.role]} · expiră pe {day(i.expires_at)}
                      </span>
                    </div>
                    <div className="row-actions">
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => void copyInvite(i)}
                      >
                        Copiază link
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => setRevoking(i)}
                      >
                        Retrage
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
        <aside className="side-col">
          <InviteForm
            locationId={locationId}
            canInviteManager={isOwner}
            onInvited={(email, url) => {
              setLinks((l) => ({ ...l, [email]: url }));
              void load();
            }}
          />
          <div className="card">
            <h2 className="h3">Ce poate face fiecare rol</h2>
            <dl className="roles">
              <dt>{ROLE_LABEL.manager}</dt>
              <dd>
                Reguli, camere, zone, confirmarea personalului, echipa (doar personal) și istoricul.
              </dd>
              <dt>{ROLE_LABEL.staff}</dt>
              <dd>Alerte pe telefon, „Preiau” și istoricul propriu.</dd>
            </dl>
          </div>
        </aside>
      </div>
      {removing && (
        <ConfirmDialog
          icon="team"
          title={`Scoți din echipa ${location?.name ?? ''}: ${removing.name}?`}
          confirmLabel="Scoate din echipă"
          onClose={() => setRemoving(null)}
          onConfirm={async () => {
            await api.removeMember(locationId, removing.user_id);
            await load();
            toast({
              title: `${removing.name} nu mai e în echipă`,
              text: 'Poți trimite oricând o invitație nouă.',
            });
          }}
        >
          <ul>
            <li>Nu mai primește alerte de la {location?.name}.</li>
            <li>Nu mai poate intra în dashboard pentru această locație.</li>
            <li>Ce a făcut până acum rămâne în Istoric.</li>
          </ul>
        </ConfirmDialog>
      )}
      {revoking && (
        <ConfirmDialog
          icon="x"
          title={`Retragi invitația pentru ${revoking.email}?`}
          confirmLabel="Retrage invitația"
          onClose={() => setRevoking(null)}
          onConfirm={async () => {
            await api.revokeInvite(revoking.id);
            await load();
            toast({
              title: 'Invitația a fost retrasă',
              text: 'Linkul trimis nu mai funcționează.',
            });
          }}
        >
          <p className="muted">
            Linkul trimis nu mai funcționează. Dacă te-ai răzgândit, poți trimite oricând unul nou.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}

function InviteForm({
  locationId,
  canInviteManager,
  onInvited,
}: {
  locationId: string;
  canInviteManager: boolean;
  onInvited: (email: string, url: string) => void;
}) {
  const api = useApi();
  const toast = useToast();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>('staff');
  const [invite, setInvite] = useState<Invite | null>(null);
  const [inviteRole, setInviteRole] = useState<Role>('staff');
  const [error, setError] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!isEmail(email))
      return setEmailError('Scrie o adresă de email validă, de exemplu ana@restaurant.ro.');
    setEmailError(null);
    setBusy(true);
    setError(null);
    try {
      const created = await api.createInvite({
        location_id: locationId,
        role,
        email: email.trim(),
      });
      setInvite(created);
      setInviteRole(role);
      onInvited(email.trim(), created.invite_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function copy() {
    if (!invite) return;
    void copyLink(
      toast,
      invite.invite_url,
      `Trimite-l pe WhatsApp sau email. Expiră pe ${day(invite.expires_at)}.`,
    );
  }

  return (
    <form className="card invite" onSubmit={submit} noValidate aria-labelledby="invite-h">
      <h2 id="invite-h" className="h3">
        Invită pe cineva
      </h2>
      <div className="field">
        <label htmlFor="invite-email">Email</label>
        <input
          id="invite-email"
          className="input"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="ospatar@restaurant.ro"
          aria-invalid={emailError ? true : undefined}
          aria-describedby={emailError ? 'invite-email-err' : undefined}
        />
        {emailError && (
          <small id="invite-email-err" className="field-error">
            {emailError}
          </small>
        )}
      </div>
      {canInviteManager ? (
        <Segmented
          label="Rol"
          value={role}
          options={[
            { value: 'staff', label: ROLE_LABEL.staff },
            { value: 'manager', label: ROLE_LABEL.manager },
          ]}
          onChange={setRole}
        />
      ) : (
        <p className="small muted">
          Invitați ca {ROLE_LABEL.staff}. Managerii îi invită proprietarul.
        </p>
      )}
      {error && <Banner tone="error" title={error} />}
      <button type="submit" className="btn btn-primary" disabled={busy}>
        Creează linkul de invitație
      </button>
      {invite && (
        <div className="invite-link" role="status">
          <span className="small muted">Linkul e gata. Expiră pe {day(invite.expires_at)}.</span>
          <div className="invite-copy">
            <input
              className="input mono"
              readOnly
              value={invite.invite_url}
              aria-label="Link de invitație"
              onFocus={(e) => e.target.select()}
            />
            <button type="button" className="btn" onClick={copy}>
              Copiază
            </button>
          </div>
          <figure className="team-qr">
            <QrCode
              value={invite.invite_url}
              label={`Cod QR pentru linkul de invitație (${ROLE_LABEL[inviteRole]})`}
            />
            <figcaption className="small muted">
              Sau scanează cu telefonul: omul își pune numele și parola, apoi primește alertele.
            </figcaption>
          </figure>
        </div>
      )}
    </form>
  );
}
