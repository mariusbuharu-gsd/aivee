import { useEffect, useId, useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import {
  MAX_VIDEO_BYTES,
  VIDEO_TYPES,
  type VideoAlert,
  type VideoRotation,
  type VideoStatus,
  type VideoUpload,
} from '../api/client';
import { useApi } from '../api/context';
import { clock, duration } from '../alerts/format';
import { Snapshot } from '../components/AlertFeed';
import { Icon } from '../components/Icon';
import { useLiveData } from '../state/context';
import { Banner } from '../ui/Banner';
import { Select } from '../ui/Select';
import { EmptyState, Skeleton } from '../ui/controls';
import { useToast } from '../ui/toast';
import { PHONE, useMedia } from '../ui/useMedia';
import { BusyLabel, Loading } from '../ui/Eyes';

/** How often the list refreshes while a clip waits or is being analysed. */
const POLL_MS = 2_000;

const STATUS: Record<VideoStatus, { label: string; pill: string }> = {
  queued: { label: 'În așteptare', pill: 'pill-muted' },
  running: { label: 'Se analizează', pill: 'pill-live' },
  done: { label: 'Gata', pill: 'pill-ok' },
  failed: { label: 'Eșuat', pill: 'pill-off' },
};

const ROTATIONS: { value: string; label: string }[] = [
  { value: '0', label: '0° (fără rotire)' },
  { value: '90', label: '90°' },
  { value: '180', label: '180°' },
  { value: '270', label: '270°' },
];

const busy = (u: VideoUpload) => u.status === 'queued' || u.status === 'running';
const message = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

/** Same checks as the API, so an obviously wrong file never leaves the browser. */
function checkVideo(file: File): string | null {
  const known = VIDEO_TYPES.includes(file.type) || /\.(mp4|mov|webm)$/i.test(file.name);
  if (!known) return 'Alege un fișier MP4, MOV sau WebM.';
  if (file.size > MAX_VIDEO_BYTES) return 'Clipul e mai mare de 200 MB. Taie-l sau micșorează-l.';
  return null;
}

const alertsLabel = (n: number) => (n === 1 ? '1 alertă' : `${n} alerte`);

export function VideoPage() {
  const api = useApi();
  const phone = useMedia(PHONE);
  const [uploads, setUploads] = useState<VideoUpload[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const timelineRef = useRef<HTMLElement>(null);

  useEffect(() => {
    let live = true;
    api
      .listVideos()
      .then((list) => live && setUploads(list))
      .catch((e: unknown) => live && setLoadError(message(e, 'Nu am putut încărca clipurile.')));
    return () => {
      live = false;
    };
  }, [api]);

  const active = (uploads ?? []).some(busy);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => {
      api.listVideos().then(setUploads, () => undefined);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [active, api]);

  const selected = uploads?.find((u) => u.id === selectedId) ?? uploads?.[0] ?? null;

  function select(id: string) {
    setSelectedId(id);
    if (phone) timelineRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }

  return (
    <div className="page">
      <header className="page-head">
        <h1>Analiză video</h1>
      </header>
      <p className="muted">
        Clipul trece prin aceleași zone și reguli ca o cameră live. Nu trimite notificări
        personalului.
      </p>
      <div className="video-grid">
        <div className="video-side">
          <UploadForm
            onUploaded={(u) => {
              setUploads((list) => [u, ...(list ?? []).filter((x) => x.id !== u.id)]);
              setSelectedId(u.id);
            }}
          />
          <section aria-labelledby="video-list-h" className="video-side">
            <h2 id="video-list-h">Clipuri</h2>
            {loadError && (
              <Banner tone="error" title="Nu am putut încărca clipurile.">
                {loadError}
              </Banner>
            )}
            {!uploads && !loadError && <Skeleton rows={2} label="Se încarcă clipurile" />}
            {uploads?.length === 0 && (
              <EmptyState icon="video" title="Niciun clip încă">
                Încarcă un clip de până la 2 minute ca să vezi ce alerte ar fi apărut.
              </EmptyState>
            )}
            {uploads && uploads.length > 0 && (
              <ul className="video-list" aria-label="Clipuri încărcate">
                {uploads.map((u) => (
                  <li key={u.id}>
                    <UploadItem
                      upload={u}
                      selected={u.id === selected?.id}
                      onSelect={() => select(u.id)}
                    />
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
        <section ref={timelineRef} className="card" aria-labelledby="video-tl-h">
          <h2 id="video-tl-h">{selected ? `Cronologie · ${selected.filename}` : 'Cronologie'}</h2>
          {selected ? (
            <Timeline upload={selected} />
          ) : (
            <p className="muted">Alege un clip ca să vezi alertele găsite în el.</p>
          )}
        </section>
      </div>
    </div>
  );
}

function UploadForm({ onUploaded }: { onUploaded: (u: VideoUpload) => void }) {
  const api = useApi();
  const toast = useToast();
  const { cameras } = useLiveData();
  const inputId = useId();
  const fileErrorId = useId();
  // Clips run as virtual cameras ("video-…"); they are not a source of zones.
  const sources = cameras.filter((c) => !c.id.startsWith('video-'));
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [source, setSource] = useState('');
  const [rotate, setRotate] = useState('0');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sourceId = sources.some((c) => c.id === source) ? source : (sources[0]?.id ?? '');

  function onFile(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    e.target.value = '';
    setFile(f);
    setError(null);
    setFileError(f ? checkVideo(f) : null);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return setFileError('Alege mai întâi un clip.');
    const problem = checkVideo(file);
    if (problem) return setFileError(problem);
    setSending(true);
    setError(null);
    try {
      const up = await api.uploadVideo({
        file,
        rotate: Number(rotate) as VideoRotation,
        copy_from_camera_id: sourceId || undefined,
      });
      onUploaded(up);
      setFile(null);
      toast({ title: `„${up.filename}” a fost trimis`, text: 'Alertele apar în cronologie.' });
    } catch (err) {
      setError(message(err, 'Nu am putut trimite clipul.'));
    } finally {
      setSending(false);
    }
  }

  return (
    <form className="card video-form" aria-labelledby="video-new-h" onSubmit={submit} noValidate>
      <h2 id="video-new-h" className="h3">
        Analizează un video
      </h2>
      <div className="upload">
        <input
          id={inputId}
          className="visually-hidden"
          type="file"
          accept={VIDEO_TYPES.join(',')}
          aria-invalid={fileError ? true : undefined}
          aria-describedby={fileErrorId}
          onChange={onFile}
        />
        <label htmlFor={inputId} className="btn">
          <Icon name="upload" /> Alege clipul
        </label>
        {file ? (
          <span className="video-name small">{file.name}</span>
        ) : (
          <span className="muted small">MP4, MOV sau WebM, cel mult 200 MB și 2 minute.</span>
        )}
        <small id={fileErrorId} className="field-error">
          {fileError}
        </small>
      </div>
      {sources.length > 0 ? (
        <Select
          label="Copiază zonele și regulile de la"
          value={sourceId}
          options={sources.map((c) => ({ value: c.id, label: c.name, hint: c.id }))}
          onChange={setSource}
        />
      ) : (
        <p className="muted small">
          Nicio cameră cu zone încă. Fără zone și reguli, clipul nu poate da alerte.
        </p>
      )}
      <Select label="Rotire" value={rotate} options={ROTATIONS} onChange={setRotate} />
      {error && (
        <Banner tone="error" title="Clipul nu a fost trimis.">
          {error}
        </Banner>
      )}
      <button type="submit" className="btn btn-primary" disabled={sending}>
        <BusyLabel busy={sending} idle="Analizează">
          Se trimite…
        </BusyLabel>
      </button>
    </form>
  );
}

function UploadItem({
  upload: u,
  selected,
  onSelect,
}: {
  upload: VideoUpload;
  selected: boolean;
  onSelect: () => void;
}) {
  const s = STATUS[u.status];
  const percent = Math.round(Math.min(1, Math.max(0, u.progress)) * 100);
  return (
    <button type="button" className="video-item" aria-pressed={selected} onClick={onSelect}>
      <span className="feed-head">
        <span className="video-name">{u.filename}</span>
        <span className={`pill ${s.pill}`}>{s.label}</span>
      </span>
      {u.status === 'running' && (
        <span
          className="progress"
          role="progressbar"
          aria-label={`Analiză ${u.filename}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
        >
          <span style={{ width: `${percent}%` }} />
        </span>
      )}
      <span className="muted small mono">
        {u.duration_s !== null ? clock(u.duration_s) : '--:--'} · {alertsLabel(u.events)}
        {u.status === 'running' ? ` · ${percent}%` : ''}
      </span>
      {u.status === 'failed' && u.error_ro && <span className="error small">{u.error_ro}</span>}
    </button>
  );
}

function Timeline({ upload }: { upload: VideoUpload }) {
  const api = useApi();
  const [alerts, setAlerts] = useState<{ id: string; items: VideoAlert[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { id, status, events } = upload;

  // Reload when the clip moves on or finds a new alert; nothing to ask while it waits.
  useEffect(() => {
    if (status === 'queued') return;
    let live = true;
    api.videoEvents(id).then(
      (items) => {
        if (!live) return;
        setAlerts({ id, items });
        setError(null);
      },
      (e: unknown) => live && setError(message(e, 'Nu am putut încărca alertele.')),
    );
    return () => {
      live = false;
    };
  }, [api, id, status, events]);

  if (status === 'queued') return <p className="muted">Clipul așteaptă la rând.</p>;
  const items = alerts?.id === id ? alerts.items : null;
  return (
    <>
      {status === 'failed' && (
        <Banner tone="error" title="Analiza a eșuat.">
          {upload.error_ro ?? 'Încearcă din nou sau cu alt clip.'}
        </Banner>
      )}
      {status === 'running' && (
        <Loading>Se analizează… alertele apar pe măsură ce sunt găsite.</Loading>
      )}
      {error && (
        <Banner tone="error" title="Nu am putut încărca alertele.">
          {error}
        </Banner>
      )}
      {!items && !error && <Skeleton rows={3} label="Se încarcă alertele" />}
      {items?.length === 0 && status !== 'running' && (
        <EmptyState icon="alerts" title="Nicio alertă în acest clip." />
      )}
      {items && items.length > 0 && (
        <ol className="feed video-timeline" aria-label="Alerte din clip">
          {items.map((a) => (
            <AlertRow key={a.event_id} alert={a} />
          ))}
        </ol>
      )}
    </>
  );
}

function AlertRow({ alert: a }: { alert: VideoAlert }) {
  const closed = a.closed_at_s !== null || a.state === 'closed';
  const steps: string[] = [];
  if (a.arrived_at_s !== null) steps.push(`ajuns ${clock(a.arrived_at_s)}`);
  if (a.closed_at_s !== null) steps.push(`închisă ${clock(a.closed_at_s)}`);
  if (a.closed_reason === 'video_end') steps.push('sfârșitul clipului');
  if (a.wait_s !== null) steps.push(`așteptare ${duration(a.wait_s)}`);
  return (
    <li className={`feed-item ${closed ? 'is-closed' : 'is-open'}`}>
      <Snapshot url={a.snapshot_url} placeholder />
      <div className="feed-body">
        <div className="feed-head">
          <span className="mono video-at">{clock(a.at_s)}</span>
          <span className="feed-zone">{a.zone_name}</span>
          <span className="video-pills">
            {!closed && <span className="pill pill-alert">Deschisă</span>}
            {a.state === 'acknowledged' && <span className="pill pill-live">Preluată</span>}
            {a.arrived_at_s !== null && <span className="pill pill-live">Ajuns</span>}
            {closed && <span className="pill pill-muted">Închisă</span>}
          </span>
        </div>
        <p className="feed-summary">{a.summary_ro}</p>
        {steps.length > 0 && <p className="muted small mono">{steps.join(' · ')}</p>}
      </div>
    </li>
  );
}
