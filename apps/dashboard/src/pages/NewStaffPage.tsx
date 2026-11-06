import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import type { StaffCapture, StaffEnrolResult } from '../api/client';
import { useApi } from '../api/context';
import { Icon } from '../components/Icon';
import { CandidateGrid, ProfileFields } from '../components/StaffCaptureParts';
import { cameraProblem, type Problem } from '../phone/problems';
import { captureBurst, grabJpeg } from '../staff/burst';
import {
  CAPTURE_SECONDS,
  NEW_PROFILE,
  useCountdown,
  useKept,
  useStaffProfiles,
} from '../staff/capture';
import { Banner } from '../ui/Banner';
import { BusyLabel } from '../ui/Eyes';
import './NewStaffPage.css';

type Facing = 'environment' | 'user';
type Step = 'name' | 'pose' | 'capturing' | 'uploading' | 'review' | 'done';

const canUseCamera = () =>
  window.isSecureContext && typeof navigator.mediaDevices?.getUserMedia === 'function';

/**
 * "Adaugă angajat" on ONE phone, without streaming: name → the phone films the employee
 * turning for 20 s (a JPEG every 1.5 s, taken here) → upload → untick crops → save.
 */
export function NewStaffPage() {
  const api = useApi();
  const profiles = useStaffProfiles();
  const [step, setStep] = useState<Step>('name');
  const [name, setName] = useState('');
  const [profileId, setProfileId] = useState(NEW_PROFILE);
  const [facing, setFacing] = useState<Facing>('environment');
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [taken, setTaken] = useState(0);
  const [capture, setCapture] = useState<StaffCapture | null>(null);
  const { kept, toggle, keepAll } = useKept();
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<StaffEnrolResult | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const left = useCountdown(step === 'capturing' ? startedAt : null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const existing = profiles.find((p) => p.id === profileId) ?? null;
  const who = existing?.name ?? name.trim();

  function releaseCamera() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }

  // Leaving the page mid-way stops the burst and frees the camera.
  useEffect(
    () => () => {
      abortRef.current?.abort();
      streamRef.current?.getTracks().forEach((t) => t.stop());
    },
    [],
  );

  async function openCamera(face: Facing) {
    releaseCamera();
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: face, width: { ideal: 1280 } },
      audio: false,
    });
    streamRef.current = stream;
    const video = videoRef.current;
    if (video) {
      video.srcObject = stream;
      await video.play().catch(() => undefined);
    }
  }

  async function toPose() {
    if (!existing && !name.trim()) return setProblem({ title: 'Scrie numele angajatului.' });
    setProblem(null);
    if (!canUseCamera()) {
      return setProblem({
        title: 'Camera merge doar pe o adresă sigură (HTTPS)',
        text: 'Deschide pagina de pe adresa https:// a aplicației.',
      });
    }
    setStep('pose');
    try {
      await openCamera(facing);
    } catch (e) {
      releaseCamera();
      setProblem(cameraProblem(e));
      setStep('name');
    }
  }

  async function flip() {
    const next: Facing = facing === 'environment' ? 'user' : 'environment';
    setFacing(next);
    try {
      await openCamera(next);
    } catch (e) {
      setProblem(cameraProblem(e));
    }
  }

  async function start() {
    setProblem(null);
    setTaken(0);
    setStartedAt(Date.now());
    setStep('capturing');
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const canvas = document.createElement('canvas');
    const shots = await captureBurst({
      seconds: CAPTURE_SECONDS,
      grab: () => grabJpeg(videoRef.current, canvas),
      onShot: setTaken,
      signal: ctrl.signal,
    });
    if (ctrl.signal.aborted) return;
    if (shots.length === 0) {
      setProblem({ title: 'Camera nu a dat nicio imagine. Încearcă din nou.' });
      return setStep('pose');
    }
    setStep('uploading');
    try {
      const c = await api.uploadStaffFrames(shots);
      releaseCamera();
      setCapture(c);
      keepAll(c);
      setStep('review');
    } catch (e) {
      setProblem({ title: e instanceof Error ? e.message : 'Trimiterea nu a mers.' });
      setStep('pose');
    }
  }

  async function again() {
    setCapture(null);
    setStep('name');
    await toPose();
  }

  async function save() {
    if (!capture || kept.size === 0) return;
    setSaving(true);
    setProblem(null);
    try {
      const r = await api.confirmStaffCapture(capture.token, {
        keep: [...kept].sort((a, b) => a - b),
        ...(existing ? { profile_id: existing.id } : { name: name.trim() }),
      });
      releaseCamera();
      setResult(r);
      setStep('done');
    } catch (e) {
      setProblem({ title: e instanceof Error ? e.message : 'Nu am putut salva profilul.' });
    } finally {
      setSaving(false);
    }
  }

  const live = step === 'pose' || step === 'capturing' || step === 'uploading';
  const stepNo = { name: 1, pose: 2, capturing: 2, uploading: 3, review: 3, done: 4 }[step];

  return (
    <div className="page new-staff">
      <header className="page-head">
        <h1>Adaugă angajat</h1>
      </header>
      <p className="muted small" aria-live="polite">
        {step === 'done' ? 'Gata' : `Pasul ${stepNo} din 4`}
      </p>

      {step === 'name' && (
        <section className="card new-staff-card">
          <ProfileFields
            profiles={profiles}
            profileId={profileId}
            onProfile={setProfileId}
            name={name}
            onName={setName}
            onEnter={() => void toPose()}
          />
          <button type="button" className="btn btn-primary" onClick={() => void toPose()}>
            Pornește camera
          </button>
        </section>
      )}

      {/* Mounted for every live step so the stream keeps its <video>. */}
      <section className="new-staff-live" hidden={!live}>
        <div className="new-staff-preview">
          <video ref={videoRef} muted playsInline autoPlay aria-label="Previzualizare cameră" />
          {step === 'capturing' && (
            <span className="staff-capture-count mono" aria-hidden="true">
              {left}
            </span>
          )}
        </div>
        <p className="staff-capture-hint">
          {step === 'pose' && (
            <>
              Cineva ține telefonul la 2–3 m; <strong>{who}</strong> stă cu tot corpul în imagine și
              se rotește încet.
            </>
          )}
          {step === 'capturing' && (
            <span role="status">
              {left > 0 ? `Rotește-te încet… încă ${left} s` : 'Ultima imagine…'} · {taken}{' '}
              {taken === 1 ? 'imagine' : 'imagini'}
            </span>
          )}
          {step === 'uploading' && <span role="status">Aleg cele mai bune imagini…</span>}
        </p>
        {step === 'capturing' && (
          <progress
            className="staff-capture-progress"
            max={CAPTURE_SECONDS}
            value={CAPTURE_SECONDS - left}
            aria-label="Captură în curs"
          />
        )}
        <div className="new-staff-actions">
          <button
            type="button"
            className="btn"
            onClick={() => void flip()}
            disabled={step !== 'pose'}
          >
            {facing === 'environment' ? 'Camera din față' : 'Camera din spate'}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void start()}
            disabled={step !== 'pose'}
          >
            <BusyLabel busy={step !== 'pose'} idle={`Start (${CAPTURE_SECONDS} s)`}>
              {step === 'uploading' ? 'Se trimite…' : 'Se capturează…'}
            </BusyLabel>
          </button>
        </div>
      </section>

      {step === 'review' && capture && (
        <section className="card new-staff-card">
          <CandidateGrid capture={capture} kept={kept} onToggle={toggle} who={who} />
          <div className="new-staff-actions">
            <button type="button" className="btn" onClick={() => void again()} disabled={saving}>
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
          </div>
        </section>
      )}

      {step === 'done' && result && (
        <section className="card new-staff-card new-staff-done">
          <Icon name="checkCircle" size={32} />
          <p role="status">
            Gata, ești recunoscut ca angajat la toate camerele.{' '}
            <span className="muted">
              Profil <strong>{result.profile.name}</strong>
              {!result.published && ', trimis camerelor offline când revin'}.
            </span>
          </p>
          <div className="new-staff-actions">
            <Link to="/alerte" className="btn">
              Înapoi la Alerte
            </Link>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setResult(null);
                setCapture(null);
                setName('');
                setProfileId(NEW_PROFILE);
                setStep('name');
              }}
            >
              Încă un angajat
            </button>
          </div>
        </section>
      )}

      {problem && (
        <Banner tone="error" title={problem.title}>
          {problem.text}
        </Banner>
      )}
    </div>
  );
}
