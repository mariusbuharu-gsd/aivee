import { useState } from 'react';
import type { CameraView, StaffCapture, StaffEnrolResult } from '../api/client';
import { useApi } from '../api/context';
import { useAuth } from '../auth/context';
import { LivePlayer } from '../live/LivePlayer';
import { isCloudFrames } from '../live/source';
import { Banner } from '../ui/Banner';
import { Dialog } from '../ui/Dialog';
import { BusyLabel } from '../ui/Eyes';
import { QrCode } from './QrCode';
import { CandidateGrid, ProfileFields } from './StaffCaptureParts';
import {
  CAPTURE_SECONDS,
  NEW_PROFILE,
  useCountdown,
  useKept,
  useStaffProfiles,
} from '../staff/capture';
import './StaffCapture.css';

type Step = 'name' | 'pose' | 'capturing' | 'review' | 'done';

/** "👔 Adaugă angajat" on a camera card; opens the guided capture. Hidden without staff.enrol. */
export function StaffCaptureButton({ camera }: { camera: CameraView }) {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  if (!can('staff.enrol')) return null;
  return (
    <>
      <button type="button" className="btn staff-capture-open" onClick={() => setOpen(true)}>
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
  const [step, setStep] = useState<Step>('name');
  const [name, setName] = useState('');
  const [profileId, setProfileId] = useState(NEW_PROFILE);
  const profiles = useStaffProfiles();
  const [capture, setCapture] = useState<StaffCapture | null>(null);
  const { kept, toggle, keepAll } = useKept();
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const left = useCountdown(step === 'capturing' ? startedAt : null);
  const phoneUrl = `${window.location.origin}/angajat-nou`;
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<StaffEnrolResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const existing = profiles.find((p) => p.id === profileId) ?? null;
  const who = existing?.name ?? name.trim();

  function toPose() {
    if (!existing && !name.trim()) return setError('Scrie numele angajatului.');
    setError(null);
    setStep('pose');
  }

  async function start() {
    setError(null);
    setStartedAt(Date.now());
    setStep('capturing');
    try {
      const c = await api.captureStaff(camera.id, CAPTURE_SECONDS);
      setCapture(c);
      keepAll(c);
      setStep('review');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Captura nu a mers. Încearcă din nou.');
      setStep('pose');
    }
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
        <>
          <ProfileFields
            profiles={profiles}
            profileId={profileId}
            onProfile={setProfileId}
            name={name}
            onName={setName}
            onEnter={toPose}
          />
          <details className="tech staff-capture-phone">
            <summary>Fă-o de pe telefon</summary>
            <QrCode value={phoneUrl} label="Cod QR pentru Adaugă angajat pe telefon" size={168} />
            <p className="muted small">
              Scanează cu telefonul și intră în cont: telefonul filmează singur, fără cameră.
            </p>
          </details>
        </>
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
        <CandidateGrid capture={capture} kept={kept} onToggle={toggle} who={who} />
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
