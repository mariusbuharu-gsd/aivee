import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { useApi } from '../api/context';
import { Icon } from '../components/Icon';
import {
  createFrameSender,
  fitWidth,
  isCloudCamera,
  type FrameSender,
  type SendStatus,
} from '../phone/sender';
import { cameraProblem, sendProblem, type Problem } from '../phone/problems';
import { useLiveData } from '../state/context';
import { Banner } from '../ui/Banner';
import { Select } from '../ui/Select';
import { EmptyState } from '../ui/controls';
import './PhoneCameraPage.css';

const FPS = 5;
const JPEG_QUALITY = 0.7;

type Facing = 'environment' | 'user';

const STATUS_RO: Record<SendStatus, string> = {
  sending: 'Trimite',
  reconnecting: 'Reconectare…',
  stopped: 'Oprit',
};

const canUseCamera = () =>
  window.isSecureContext && typeof navigator.mediaDevices?.getUserMedia === 'function';

/** Turns this phone's browser into a cloud camera: no laptop, no app. */
export function PhoneCameraPage() {
  const api = useApi();
  const { cameras, loading } = useLiveData();
  const [params, setParams] = useSearchParams();
  const wanted = params.get('camera');
  const cloud = cameras.filter(isCloudCamera);
  const cameraId = wanted ?? cloud[0]?.id ?? '';
  const camera = cameras.find((c) => c.id === cameraId) ?? null;

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const senderRef = useRef<FrameSender | null>(null);
  const wakeRef = useRef<WakeLockSentinel | null>(null);
  const [facing, setFacing] = useState<Facing>('environment');
  const [running, setRunning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [status, setStatus] = useState<SendStatus>('stopped');
  const [fps, setFps] = useState(0);
  const [sent, setSent] = useState(0);
  const [problem, setProblem] = useState<Problem | null>(null);

  function releaseCamera() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }

  async function lockScreen() {
    try {
      wakeRef.current = (await navigator.wakeLock?.request('screen')) ?? null;
    } catch {
      /* low battery or not allowed: the phone may dim, frames still go out while it is on */
    }
  }

  function stop() {
    senderRef.current?.stop();
    senderRef.current = null;
    releaseCamera();
    void wakeRef.current?.release().catch(() => undefined);
    wakeRef.current = null;
    setRunning(false);
    setFps(0);
  }

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

  async function start() {
    if (!camera) return;
    setProblem(null);
    if (!canUseCamera()) {
      setProblem({
        title: 'Camera merge doar pe o adresă sigură (HTTPS)',
        text: 'Deschide pagina de pe adresa https:// a aplicației.',
      });
      return;
    }
    setStarting(true);
    try {
      await openCamera(facing);
    } catch (e) {
      releaseCamera();
      setProblem(cameraProblem(e));
      return;
    } finally {
      setStarting(false);
    }
    const canvas = document.createElement('canvas');
    const id = camera.id;
    const sender = createFrameSender({
      fps: FPS,
      capture: () => grab(videoRef.current, canvas),
      send: (jpeg) => api.pushFrame(id, jpeg),
      onStatus: setStatus,
      onStats: (s) => {
        setFps(s.fps);
        setSent(s.sent);
      },
      onFatal: (e) => {
        stop();
        setProblem(sendProblem(e));
      },
    });
    senderRef.current = sender;
    sender.start();
    setRunning(true);
    void lockScreen();
  }

  async function flip() {
    const next: Facing = facing === 'environment' ? 'user' : 'environment';
    setFacing(next);
    if (!running) return;
    try {
      await openCamera(next);
    } catch (e) {
      stop();
      setProblem(cameraProblem(e));
    }
  }

  // The wake lock is dropped whenever the page is hidden; take it again on return.
  useEffect(() => {
    if (!running) return;
    const onVisible = () => {
      if (document.visibilityState === 'visible') void lockScreen();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [running]);

  // Leaving the page (or switching location) releases the camera.
  useEffect(() => () => stop(), []); // eslint-disable-line react-hooks/exhaustive-deps

  const next = `/telefon${camera ? `?camera=${encodeURIComponent(camera.id)}` : ''}`;

  return (
    <div className="page phone-page">
      <header className="page-head">
        <h1>Telefonul ca cameră</h1>
      </header>
      <p className="muted">
        Pune telefonul pe un suport, cu sala în cadru. Imaginile merg direct la server; nu trebuie
        instalat nimic.
      </p>

      {!loading && cloud.length === 0 && !camera && (
        <EmptyState icon="devices" title="Nicio cameră cloud la această locație">
          Adaugă la <Link to="/dispozitive">Camere</Link> o cameră cu sursa{' '}
          <span className="mono">mqtt-frames://&lt;id&gt;</span>, apoi revino aici.
        </EmptyState>
      )}

      {(cloud.length > 0 || camera) && (
        <Select
          label="Camera"
          value={cameraId}
          disabled={running}
          options={(camera && !cloud.includes(camera) ? [camera, ...cloud] : cloud).map((c) => ({
            value: c.id,
            label: c.name,
            hint: c.id,
          }))}
          onChange={(v) => setParams({ camera: v }, { replace: true })}
        />
      )}
      {wanted && !loading && !camera && (
        <Banner tone="warn" title={`Camera ${wanted} nu există la această locație`} />
      )}
      {camera && !isCloudCamera(camera) && (
        <Banner tone="warn" title="Camera aceasta nu primește imagini de la telefon">
          Sursa ei e <span className="mono">{camera.source.split('://')[0]}://…</span>. Alege o
          cameră cu sursa <span className="mono">mqtt-frames://{camera.id}</span>.
        </Banner>
      )}

      <div className="phone-preview on-night">
        <video ref={videoRef} muted playsInline autoPlay aria-label="Previzualizare cameră" />
        {!running && <span className="phone-preview-idle">Camera e oprită</span>}
        <span
          className={`pill phone-status ${status === 'sending' ? 'pill-live' : 'pill-off'}`}
          role="status"
        >
          {/* One child: the pill is a flex box, which would drop the spaces between parts. */}
          <span>
            {STATUS_RO[running ? status : 'stopped']}
            {running && (
              <>
                {' · '}
                <span className="mono">{fps}</span> cadre/s
              </>
            )}
          </span>
        </span>
      </div>

      {problem && (
        <Banner
          tone="error"
          title={problem.title}
          action={
            problem.login ? (
              <Link className="btn btn-sm" to={`/intra?next=${encodeURIComponent(next)}`}>
                Intră în cont
              </Link>
            ) : undefined
          }
        >
          {problem.text}
        </Banner>
      )}

      <div className="phone-actions">
        {running ? (
          <button type="button" className="btn phone-btn" onClick={stop}>
            <Icon name="x" /> Oprește
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-primary phone-btn"
            onClick={() => void start()}
            disabled={!camera || starting}
          >
            <Icon name="live" /> {starting ? 'Pornește…' : 'Pornește camera'}
          </button>
        )}
        <button type="button" className="btn phone-btn" onClick={() => void flip()}>
          <Icon name="undo" /> {facing === 'environment' ? 'Camera din față' : 'Camera din spate'}
        </button>
      </div>
      {running && (
        <p className="small muted">
          Trimise: <span className="mono">{sent}</span>. Ține ecranul deschis; dacă blochezi
          telefonul, imaginile se opresc.
        </p>
      )}
    </div>
  );
}

/** The current video picture as a JPEG at most 640 px wide; null until the video has a frame. */
function grab(video: HTMLVideoElement | null, canvas: HTMLCanvasElement): Promise<Blob | null> {
  if (!video || video.readyState < 2 || !video.videoWidth) return Promise.resolve(null);
  const { width, height } = fitWidth(video.videoWidth, video.videoHeight);
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) return Promise.resolve(null);
  ctx.drawImage(video, 0, 0, width, height);
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY));
}
