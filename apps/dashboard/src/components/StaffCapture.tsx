import { useEffect, useId, useState } from 'react';
import type { CameraView, StaffCapture, StaffEnrolResult, StaffProfile } from '../api/client';
import { useApi } from '../api/context';
import { useAuth } from '../auth/context';
import { LivePlayer } from '../live/LivePlayer';
import { isCloudFrames } from '../live/source';
import { Banner } from '../ui/Banner';
import { Dialog } from '../ui/Dialog';
import { BusyLabel } from '../ui/Eyes';
import { Select } from '../ui/Select';
import { Icon } from './Icon';
import './StaffCapture.css';

/** How long the camera watches the employee turn around (the API accepts 5–30 s). */
export const CAPTURE_SECONDS = 20;
const NEW_PROFILE = '';

type Step = 'name' | 'pose' | 'capturing' | 'review' | 'done';

/** "👔 Adaugă angajat" on a camera card; opens the guided capture. Hidden without staff.enrol. */
export function StaffCaptureButton({ camera }: { camera: CameraView }) {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  if (!can('staff.enrol')) return null;
  return (
    <>
      <button type="button" className="btn" onClick={() => setOpen(true)}>
        <span aria-hidden="true">👔</span> Adaugă angajat
      </button>
      {open && <StaffCaptureDialog camera={camera} onClose={() => setOpen(false)} />}
    </>
  );
}

/**
 * "Adaugă angajat în 20 de secunde": name → stand in front of the camera → the camera samples
 * the largest person for 20 s → untick bad crops → save, which publishes the profile to the edges.
 */
export function StaffCaptureDialog({
  camera,
  onClose,
}: {
  camera: CameraView;
  onClose: () => void;
}) {
  const api = useApi();
  const nameId = useId();
  const [step, setStep] = useState<Step>('name');
  const [name, setName] = useState('');
  const [profileId, setProfileId] = useState(NEW_PROFILE);
  const [profiles, setProfiles] = useState<StaffProfile[]>([]);
  const [capture, setCapture] = useState<StaffCapture | null>(null);
  const [kept, setKept] = useState<Set<number>>(new Set());
  const [left, setLeft] = useState(CAPTURE_SECONDS);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<StaffEnrolResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.listStaffProfiles().then(
      (p) => alive && setProfiles(p),
      () => undefined, // adding to an existing profile is optional
    );
    return () => {
      alive = false;
    };
  }, [api]);

  useEffect(() => {
    if (step !== 'capturing') return;
    const started = Date.now();
    const timer = setInterval(() => {
      setLeft(Math.max(0, CAPTURE_SECONDS - Math.floor((Date.now() - started) / 1000)));
    }, 250);
    return () => clearInterval(timer);
  }, [step]);

  const existing = profiles.find((p) => p.id === profileId) ?? null;
  const who = existing?.name ?? name.trim();

  function toPose() {
    if (!existing && !name.trim()) return setError('Scrie numele angajatului.');
    setError(null);
    setStep('pose');
  }

  async function start() {
    setError(null);
    setLeft(CAPTURE_SECONDS);
    setStep('capturing');
    try {
      const c = await api.captureStaff(camera.id, CAPTURE_SECONDS);
      setCapture(c);
      setKept(new Set(c.candidates.map((x) => x.index)));
      setStep('review');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Captura nu a mers. Încearcă din nou.');
      setStep('pose');
    }
  }

  function toggle(index: number) {
    setKept((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  async function save() {
    if (!capture || kept.size === 0) return;
    setSaving(true);
    setError(null);
    try {
      const r = await api.confirmStaffCapture(capture.token, {
        keep: [...kept].sort((a, b) => a - b),
        ...(existing ? { profile_id: existing.id } : { name: name.trim() }),
      });
      setResult(r);
      setStep('done');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Nu am putut salva profilul.');
    } finally {
      setSaving(false);
    }
  }

  const busy = step === 'capturing' || saving;
  const close = () => !busy && onClose();
  const stepNo = { name: 1, pose: 2, capturing: 2, review: 3, done: 4 }[step];

  return (
    <Dialog
      title={step === 'done' ? 'Gata!' : 'Adaugă angajat'}
      icon={step === 'done' ? 'checkCircle' : 'team'}
      className="dialog-sheet staff-capture"
      onClose={close}
      actions={renderActions()}
    >
      <p className="staff-capture-step muted small" aria-live="polite">
        {step === 'done' ? camera.name : `Pasul ${stepNo} din 4 · ${camera.name}`}
      </p>

      {step === 'name' && (
        <div className="stack-form">
          {profiles.length > 0 && (
            <Select
              label="Profil"
              value={profileId}
              onChange={setProfileId}
              options={[
                { value: NEW_PROFILE, label: 'Angajat nou' },
                ...profiles.map((p) => ({
                  value: p.id,
                  label: p.name,
                  hint: `${p.examples} ${p.examples === 1 ? 'exemplu' : 'exemple'}`,
                })),
              ]}
            />
          )}
          {!existing && (
            <label className="field" htmlFor={nameId}>
              <span>Nume</span>
              <input
                id={nameId}
                className="input"
                value={name}
                maxLength={80}
                autoComplete="off"
                placeholder="ex. Ana, ospătar"
                data-autofocus
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') toPose();
                }}
              />
            </label>
          )}
          {existing && <p className="small">Adăugăm imagini noi la profilul „{existing.name}”.</p>}
        </div>
      )}

      {(step === 'pose' || step === 'capturing') && (
        <div className="staff-capture-live">
          <div className="tile-media staff-capture-media">
            <LivePlayer
              cameraId={camera.id}
              enabled
              label={camera.name}
              mjpegUrl={api.liveMjpegUrl(camera.id)}
              cloudFrames={isCloudFrames(camera.source)}
            />
            {step === 'capturing' && (
              <span className="staff-capture-count mono" aria-hidden="true">
                {left}
              </span>
            )}
          </div>
          <p className="staff-capture-hint">
            {step === 'capturing' ? (
              <span role="status">
                {left > 0 ? `Rotește-te încet… încă ${left} s` : 'Aleg cele mai bune imagini…'}
              </span>
            ) : (
              <>
                <strong>{who}</strong>, stai în fața camerei, cu tot corpul în imagine, și
                rotește-te încet.
              </>
            )}
          </p>
          {step === 'capturing' && (
            <progress
              className="staff-capture-progress"
              max={CAPTURE_SECONDS}
              value={CAPTURE_SECONDS - left}
              aria-label="Captură în curs"
            />
          )}
        </div>
      )}

      {step === 'review' && capture && (
        <>
          <p className="small">
            Am găsit {capture.candidates.length}{' '}
            {capture.candidates.length === 1 ? 'imagine' : 'imagini'} cu {who}. Atinge una ca să o
            scoți (alte persoane, imagini neclare).
          </p>
          <ul className="staff-capture-grid">
            {capture.candidates.map((c) => {
              const on = kept.has(c.index);
              return (
                <li key={c.index}>
                  <button
                    type="button"
                    className={`staff-capture-thumb ${on ? 'is-on' : 'is-off'}`}
                    aria-pressed={on}
                    aria-label={`Imaginea ${c.index + 1}${on ? ', păstrată' : ', scoasă'}`}
                    onClick={() => toggle(c.index)}
                  >
                    <img src={c.thumbnail} alt="" />
                    <span className="staff-capture-tick" aria-hidden="true">
                      <Icon name={on ? 'check' : 'x'} size={16} />
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <p className="muted small">
            Păstrezi {kept.size} din {capture.candidates.length}. Fețele nu sunt folosite, doar
            ținuta.
          </p>
        </>
      )}

      {step === 'done' && result && (
        <p role="status">
          Profil publicat la camere: <strong>{result.profile.name}</strong>, {result.examples_added}{' '}
          {result.examples_added === 1 ? 'imagine nouă' : 'imagini noi'}
          {!result.published && ' (camerele îl primesc când revin online)'}.
        </p>
      )}

      {error && <Banner tone="error" title={error} />}
    </Dialog>
  );

  function renderActions() {
    if (step === 'name')
      return (
        <>
          <button type="button" className="btn" onClick={onClose}>
            Renunță
          </button>
          <button type="button" className="btn btn-primary" onClick={toPose}>
            Mai departe
          </button>
        </>
      );
    if (step === 'pose' || step === 'capturing')
      return (
        <>
          <button type="button" className="btn" onClick={() => setStep('name')} disabled={busy}>
            Înapoi
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void start()}
            disabled={busy}
          >
            <BusyLabel busy={step === 'capturing'} idle={`Start (${CAPTURE_SECONDS} s)`}>
              Se capturează…
            </BusyLabel>
          </button>
        </>
      );
    if (step === 'review')
      return (
        <>
          <button type="button" className="btn" onClick={() => setStep('pose')} disabled={saving}>
            Reia
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void save()}
            disabled={saving || kept.size === 0}
          >
            <BusyLabel busy={saving} idle="Salvează">
              Se salvează…
            </BusyLabel>
          </button>
        </>
      );
    return (
      <button type="button" className="btn btn-primary" onClick={onClose} data-autofocus>
        Închide
      </button>
    );
  }
}
