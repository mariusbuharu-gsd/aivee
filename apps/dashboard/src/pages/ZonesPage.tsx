import { useEffect, useState, type CSSProperties, type MouseEvent } from 'react';
import { Link, useParams } from 'react-router';
import { useApi } from '../api/context';
import { Icon } from '../components/Icon';
import type { Zone } from '../contracts';
import { LivePlayer, type PlayerStatus } from '../live/LivePlayer';
import { ZONE_TAGS, tagLabel } from '../rules/describe';
import { useLiveData } from '../state/context';
import {
  addPoint,
  closeDraft,
  deleteZone,
  draftToZone,
  emptyDraft,
  hitTest,
  normaliseClick,
  toSvgPoints,
  undoPoint,
  updateZone,
  type Draft,
} from '../zones/geometry';

const newId = () => `z-${Date.now().toString(36)}`;

export function ZonesPage() {
  const { cameraId = '' } = useParams();
  const { cameras, loading } = useLiveData();
  const camera = cameras.find((c) => c.id === cameraId);
  if (!camera) {
    return (
      <div className="page">
        <p className="muted">{loading ? 'Se încarcă…' : 'Camera nu a fost găsită.'}</p>
        <Link to="/" className="link">
          Înapoi la Live
        </Link>
      </div>
    );
  }
  // Remount the editor per camera so its local draft state never leaks between cameras.
  return <ZoneEditor key={camera.id} cameraId={camera.id} />;
}

function ZoneEditor({ cameraId }: { cameraId: string }) {
  const api = useApi();
  const { cameras, setZones } = useLiveData();
  const camera = cameras.find((c) => c.id === cameraId);
  const [zones, setLocal] = useState<Zone[]>(camera?.zones ?? []);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [redrawId, setRedrawId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [tag, setTag] = useState('table');
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [live, setLive] = useState<PlayerStatus>('connecting');
  // A still the user picked; kept only in this browser as the drawing background.
  const [still, setStill] = useState<string | null>(null);
  const [frame, setFrame] = useState<[number, number] | null>(null);

  useEffect(() => () => void (still && URL.revokeObjectURL(still)), [still]);

  if (!camera) return null;
  const current = zones.find((z) => z.id === selected) ?? null;

  const change = (next: Zone[]) => {
    setLocal(next);
    setDirty(true);
    setStatus(null);
  };

  function onSurfaceClick(e: MouseEvent<SVGSVGElement>) {
    const p = normaliseClick(e.clientX, e.clientY, e.currentTarget.getBoundingClientRect());
    if (draft) {
      setDraft(addPoint(draft, p));
      return;
    }
    setSelected(hitTest(p, zones));
  }

  function startDrawing(replace: string | null = null) {
    setDraft(emptyDraft());
    setRedrawId(replace);
    if (!replace) {
      setSelected(null);
      setName(`Masa ${zones.filter((z) => z.tag === 'table').length + 1}`);
      setTag('table');
    }
  }

  function finishDraft() {
    if (!draft) return;
    if (redrawId) {
      const z = draftToZone(draft, {
        id: redrawId,
        name: current?.name ?? 'Zonă',
        tag: current?.tag ?? 'table',
      });
      if (z) change(updateZone(zones, redrawId, { polygon: z.polygon }));
    } else {
      const z = draftToZone(draft, { id: newId(), name, tag });
      if (!z) return;
      change([...zones, z]);
      setSelected(z.id);
    }
    setDraft(null);
    setRedrawId(null);
  }

  async function save() {
    if (!camera) return;
    setSaving(true);
    try {
      const saved = await api.saveZones(camera.id, zones);
      setZones(camera.id, saved);
      setDirty(false);
      setStatus('Zonele au fost salvate și trimise dispozitivului.');
    } catch (e) {
      setStatus(e instanceof Error ? e.message : 'Salvarea a eșuat');
    } finally {
      setSaving(false);
    }
  }

  const canFinish = draft?.closed && (redrawId !== null || name.trim() !== '');
  const editorStyle: CSSProperties | undefined = frame
    ? { aspectRatio: `${frame[0]} / ${frame[1]}` }
    : undefined;

  function pickStill(file: File | undefined) {
    if (!file || !file.type.startsWith('image/')) return;
    setFrame(null);
    setStill(URL.createObjectURL(file));
  }

  const stillPicker = (
    <label className="btn">
      <Icon name="upload" /> {still ? 'Altă imagine' : 'Încarcă o imagine'}
      <input
        type="file"
        accept="image/*"
        className="visually-hidden"
        aria-label="Încarcă o imagine din cameră"
        onChange={(e) => {
          pickStill(e.target.files?.[0]);
          e.target.value = '';
        }}
      />
    </label>
  );

  return (
    <div className="page">
      <header className="page-head">
        <h1>
          Zone · <span className="muted">{camera.name}</span>
        </h1>
        <button className="btn btn-primary" onClick={save} disabled={!dirty || saving}>
          {saving ? 'Se salvează…' : 'Salvează zonele'}
        </button>
      </header>
      {status && (
        <p className="small" role="status">
          {status}
        </p>
      )}
      <div className="two-col">
        <section aria-label="Imagine cameră">
          <div className={`editor ${draft ? 'is-drawing' : ''}`} style={editorStyle}>
            {still ? (
              <img
                className="editor-still"
                src={still}
                alt={`Imagine încărcată pentru ${camera.name}`}
                onLoad={(e) =>
                  setFrame([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])
                }
              />
            ) : (
              // Try MediaMTX even if the device has not reported online yet: the stream may be up.
              <LivePlayer
                cameraId={camera.id}
                label={camera.name}
                onStatus={setLive}
                onFrameSize={(w, h) => w > 0 && h > 0 && setFrame([w, h])}
              />
            )}
            <svg
              className="overlay overlay-edit"
              viewBox="0 0 1 1"
              preserveAspectRatio="none"
              onClick={onSurfaceClick}
              aria-label={
                draft ? 'Click pentru a adăuga un punct' : 'Click pe o zonă pentru a o selecta'
              }
              role="application"
            >
              {zones.map((z) => (
                <polygon
                  key={z.id}
                  points={toSvgPoints(z.polygon)}
                  className={`zone-shape zone-${z.tag} ${z.id === selected ? 'is-selected' : ''}`}
                />
              ))}
              {draft && draft.points.length > 0 && (
                <>
                  {draft.closed ? (
                    <polygon points={toSvgPoints(draft.points)} className="zone-draft" />
                  ) : (
                    <polyline points={toSvgPoints(draft.points)} className="zone-draft" />
                  )}
                  {draft.points.map(([x, y], i) => (
                    <circle
                      key={i}
                      cx={x}
                      cy={y}
                      r={i === 0 ? 0.014 : 0.009}
                      className={i === 0 ? 'vertex vertex-first' : 'vertex'}
                    />
                  ))}
                </>
              )}
            </svg>
            {zones.map((z) => {
              const [x, y] = z.polygon[0];
              return (
                <span
                  key={z.id}
                  className="zone-tagline mono"
                  style={{ left: `${x * 100}%`, top: `${y * 100}%` }}
                >
                  {z.name}
                </span>
              );
            })}
          </div>
          <div className="toolbar">
            {draft ? (
              <>
                <span className="muted small" aria-live="polite">
                  {draft.closed
                    ? 'Poligon închis.'
                    : `${draft.points.length} puncte · click pe primul punct sau „Închide” pentru a termina`}
                </span>
                <button
                  className="btn"
                  onClick={() => setDraft(undoPoint(draft))}
                  disabled={draft.points.length === 0}
                >
                  <Icon name="undo" /> Anulează punctul
                </button>
                <button
                  className="btn"
                  onClick={() => setDraft(closeDraft(draft))}
                  disabled={draft.closed || draft.points.length < 3}
                >
                  <Icon name="close" /> Închide poligonul
                </button>
                <button
                  className="btn btn-ghost"
                  onClick={() => {
                    setDraft(null);
                    setRedrawId(null);
                  }}
                >
                  Renunță
                </button>
              </>
            ) : (
              <button className="btn btn-primary" onClick={() => startDrawing()}>
                <Icon name="zones" /> Desenează o zonă
              </button>
            )}
          </div>
        </section>

        <aside className="side-col">
          <div className="card">
            <h2 className="h3">Fundal</h2>
            <p className="muted small" role="status">
              {still
                ? 'Desenezi pe imaginea încărcată (rămâne doar în acest browser).'
                : live === 'playing'
                  ? 'Desenezi pe imaginea live a camerei.'
                  : live === 'connecting'
                    ? 'Se conectează la camera live…'
                    : 'Fluxul live nu e disponibil. Încarcă o captură din cameră ca să desenezi mesele exact.'}
            </p>
            <div className="actions">
              {stillPicker}
              {still && (
                <button
                  className="btn btn-ghost"
                  onClick={() => {
                    setStill(null);
                    setFrame(null);
                  }}
                >
                  Folosește imaginea live
                </button>
              )}
            </div>
          </div>
          {draft && !redrawId && (
            <form
              className="card"
              onSubmit={(e) => {
                e.preventDefault();
                finishDraft();
              }}
            >
              <h2 className="h3">Zonă nouă</h2>
              <ZoneFields name={name} tag={tag} onName={setName} onTag={setTag} />
              <button className="btn btn-primary" type="submit" disabled={!canFinish}>
                Adaugă zona
              </button>
            </form>
          )}
          {draft && redrawId && (
            <div className="card">
              <h2 className="h3">Redesenezi „{current?.name}”</h2>
              <button className="btn btn-primary" onClick={finishDraft} disabled={!canFinish}>
                Păstrează noul contur
              </button>
            </div>
          )}
          {!draft && current && (
            <div className="card">
              <h2 className="h3">Editează zona</h2>
              <ZoneFields
                name={current.name}
                tag={current.tag}
                onName={(v) => change(updateZone(zones, current.id, { name: v }))}
                onTag={(v) => change(updateZone(zones, current.id, { tag: v }))}
              />
              <div className="actions">
                <button className="btn" onClick={() => startDrawing(current.id)}>
                  <Icon name="edit" /> Redesenează
                </button>
                <button
                  className="btn btn-danger"
                  onClick={() => {
                    change(deleteZone(zones, current.id));
                    setSelected(null);
                  }}
                >
                  <Icon name="trash" /> Șterge
                </button>
              </div>
            </div>
          )}
          <section aria-labelledby="zones-h">
            <h2 id="zones-h">Zone ({zones.length})</h2>
            {zones.length === 0 && (
              <p className="muted">Nicio zonă. Desenează masa sau intrarea pe imagine.</p>
            )}
            <ul className="zone-list">
              {zones.map((z) => (
                <li key={z.id}>
                  <button
                    className={`zone-row ${z.id === selected ? 'is-selected' : ''}`}
                    aria-pressed={z.id === selected}
                    onClick={() => {
                      setDraft(null);
                      setSelected(z.id);
                    }}
                  >
                    <span className={`swatch zone-${z.tag}`} aria-hidden="true" />
                    <span>{z.name}</span>
                    <span className="muted small">{tagLabel(z.tag)}</span>
                    <span className="muted small mono">{z.polygon.length} puncte</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>
    </div>
  );
}

function ZoneFields({
  name,
  tag,
  onName,
  onTag,
}: {
  name: string;
  tag: string;
  onName: (v: string) => void;
  onTag: (v: string) => void;
}) {
  return (
    <>
      <label className="field">
        <span>Nume</span>
        <input className="input" value={name} onChange={(e) => onName(e.target.value)} required />
      </label>
      <label className="field">
        <span>Tip</span>
        <select className="input" value={tag} onChange={(e) => onTag(e.target.value)}>
          {ZONE_TAGS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}
