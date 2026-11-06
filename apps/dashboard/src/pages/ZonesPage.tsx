import { useEffect, useState, type CSSProperties, type MouseEvent } from 'react';
import { Link, useParams } from 'react-router';
import { useApi } from '../api/context';
import { Icon } from '../components/Icon';
import type { Zone } from '../contracts';
import { LivePlayer, type PlayerStatus } from '../live/LivePlayer';
import { ZONE_TAGS, tagLabel } from '../rules/describe';
import { useLiveData } from '../state/context';
import { useLeaveGuard } from '../state/leaveGuard';
import { Banner } from '../ui/Banner';
import { Dialog } from '../ui/Dialog';
import { Segmented, Skeleton } from '../ui/controls';
import { useToast } from '../ui/toast';
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
import './ZonesPage.css';

const newId = () => `z-${Date.now().toString(36)}`;

const BASE_NAME: Record<string, string> = { table: 'Masa', entrance: 'Intrare' };
/** Short labels for the toolbar on the image; the kinds come from ZONE_TAGS. */
const TOOL_LABEL: Record<string, string> = { staff: 'Personal' };

/** "Masa 3", "Intrare 2", "Zonă personal": the next free name for a zone of this kind. */
function defaultName(zones: Zone[], tag: string): string {
  const base = BASE_NAME[tag] ?? tagLabel(tag);
  const n = zones.filter((z) => z.tag === tag).length;
  return tag === 'table' || n > 0 ? `${base} ${n + 1}` : base;
}

/** "1 zonă", "3 zone", "20 de zone". */
function countZones(n: number): string {
  if (n === 1) return '1 zonă';
  const r = n % 100;
  return n >= 20 && (r === 0 || r >= 20) ? `${n} de zone` : `${n} zone`;
}

export function ZonesPage() {
  const { cameraId = '' } = useParams();
  const { cameras, loading } = useLiveData();
  const camera = cameras.find((c) => c.id === cameraId);
  if (!camera) {
    return (
      <div className="page">
        {loading ? (
          <Skeleton rows={2} label="Se încarcă camera" />
        ) : (
          <p className="muted">Camera nu a fost găsită.</p>
        )}
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
  const [warnings, setWarnings] = useState<string[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [leaving, setLeaving] = useState<(() => void) | null>(null);
  const toast = useToast();
  useLeaveGuard(
    dirty
      ? (proceed) => {
          setLeaving(() => proceed);
          return true;
        }
      : null,
  );
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
    setSaveError(null);
  };

  function onSurfaceClick(e: MouseEvent<SVGSVGElement>) {
    const p = normaliseClick(e.clientX, e.clientY, e.currentTarget.getBoundingClientRect());
    if (draft) {
      setDraft(addPoint(draft, p));
      return;
    }
    setSelected(hitTest(p, zones));
  }

  function startDrawing(replace: string | null = null, kind = 'table') {
    setRedrawId(replace);
    if (replace) {
      setDraft(emptyDraft());
      return;
    }
    // Switching the tool mid-draw keeps the points; a name the user typed stays too.
    if (!draft || redrawId) setDraft(emptyDraft());
    setSelected(null);
    if (!draft || redrawId || name === defaultName(zones, tag)) setName(defaultName(zones, kind));
    setTag(kind);
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

  async function save(): Promise<boolean> {
    if (!camera) return false;
    setSaving(true);
    setSaveError(null);
    try {
      const saved = await api.saveZones(camera.id, zones);
      setZones(camera.id, saved.zones);
      setLocal(saved.zones);
      setDirty(false);
      setWarnings(saved.warnings_ro);
      const n = saved.zones.length;
      toast({
        title: n === 1 ? 'O zonă salvată' : `${n} zone salvate`,
        text: `${camera.name} folosește zonele noi de acum.`,
      });
      return true;
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Salvarea a eșuat.');
      return false;
    } finally {
      setSaving(false);
    }
  }

  function removeZone(id: string) {
    const before = zones;
    const gone = zones.find((z) => z.id === id);
    change(deleteZone(zones, id));
    setSelected(null);
    toast({
      kind: 'undo',
      title: `Zona „${gone?.name ?? ''}” a fost ștearsă`,
      text: 'Se salvează abia când apeși „Salvează zonele”.',
      action: {
        label: 'Anulează',
        run: () => {
          setLocal(before);
          setSelected(id);
        },
      },
    });
  }

  const canFinish = draft?.closed && (redrawId !== null || name.trim() !== '');
  const drawTag = redrawId ? (current?.tag ?? 'table') : tag;
  const editorStyle: CSSProperties | undefined = frame
    ? { aspectRatio: `${frame[0]} / ${frame[1]}` }
    : undefined;

  function pickStill(file: File | undefined) {
    if (!file || !file.type.startsWith('image/')) return;
    setFrame(null);
    setStill(URL.createObjectURL(file));
  }

  // No live picture: one quiet line on the canvas offers a capture instead of a whole card.
  const showSource = !!still || (live !== 'playing' && live !== 'connecting');
  const stillPicker = (
    <label className="zone-source-pick">
      {still ? 'Schimbă' : 'Încarcă o captură'}
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
    <div className="page zones-page">
      <header className="page-head">
        <h1>
          Zone · <span className="muted">{camera.name}</span>
        </h1>
        <div className="actions zones-save">
          {dirty || saving ? (
            <>
              <span className="zones-state is-dirty" role="status">
                {saving ? 'se salvează…' : 'modificări nesalvate'}
              </span>
              <button className="btn btn-primary" onClick={() => void save()} disabled={saving}>
                {saving ? 'Se salvează…' : 'Salvează zonele'}
              </button>
            </>
          ) : (
            <>
              <span className="zones-state is-saved" role="status">
                <Icon name="check" /> salvat
              </span>
              <Link to="/dispozitive" className="btn">
                Gata
              </Link>
            </>
          )}
        </div>
      </header>
      {saveError && (
        <Banner
          tone="error"
          title="Zonele nu s-au salvat."
          action={
            <button type="button" className="btn btn-sm" onClick={() => void save()}>
              Reîncearcă
            </button>
          }
        >
          {saveError} Modificările rămân aici.
        </Banner>
      )}
      {warnings.length > 0 && (
        <Banner tone="warn" title="Zonele s-au salvat, dar verifică:">
          {warnings.join(' ')}
        </Banner>
      )}
      <div className="two-col">
        <section aria-label="Imagine cameră">
          <div className={`editor-wrap draw-${drawTag}`}>
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
                      <polygon
                        points={toSvgPoints(draft.points)}
                        className={`zone-draft zone-${drawTag}`}
                      />
                    ) : (
                      <polyline
                        points={toSvgPoints(draft.points)}
                        className={`zone-draft zone-${drawTag}`}
                      />
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
              {showSource && (
                <p className="zone-source" role="status">
                  {still ? 'Captură încărcată' : 'Imagine de probă'} · {stillPicker}
                </p>
              )}
            </div>
            <div className="zone-tools" role="toolbar" aria-label="Unelte de desen">
              {ZONE_TAGS.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  className={`zone-tool zone-${t.value}`}
                  aria-pressed={!!draft && !redrawId && tag === t.value}
                  disabled={!!redrawId}
                  onClick={() => startDrawing(null, t.value)}
                >
                  <span className={`swatch zone-${t.value}`} aria-hidden="true" />
                  {TOOL_LABEL[t.value] ?? t.label}
                </button>
              ))}
              {draft && (
                <>
                  <span className="zone-tools-sep" aria-hidden="true" />
                  <button
                    type="button"
                    className="zone-tool"
                    aria-label="Anulează punctul"
                    title="Anulează punctul"
                    onClick={() => setDraft(undoPoint(draft))}
                    disabled={draft.points.length === 0}
                  >
                    <Icon name="undo" />
                  </button>
                  <button
                    type="button"
                    className="zone-tool"
                    onClick={() => setDraft(closeDraft(draft))}
                    disabled={draft.closed || draft.points.length < 3}
                  >
                    Închide
                  </button>
                  <button
                    type="button"
                    className="zone-tool"
                    onClick={() => {
                      setDraft(null);
                      setRedrawId(null);
                    }}
                  >
                    Renunță
                  </button>
                </>
              )}
            </div>
          </div>
          <p className="zones-hint muted small" aria-live="polite">
            {!draft
              ? 'Alege Masă, Intrare sau Personal, apoi dă click pe colțurile zonei.'
              : draft.closed
                ? 'Poligon închis. Pune-i un nume în dreapta și adaug-o.'
                : `${draft.points.length} puncte · click pe primul punct sau „Închide” pentru a termina`}
          </p>
        </section>

        <aside className="side-col zone-panel">
          {draft && !redrawId && (
            <form
              className="zone-panel-block"
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
            <div className="zone-panel-block">
              <h2 className="h3">Redesenezi „{current?.name}”</h2>
              <button className="btn btn-primary" onClick={finishDraft} disabled={!canFinish}>
                Păstrează noul contur
              </button>
            </div>
          )}
          {!draft && current && (
            <div className="zone-panel-block">
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
                <button className="btn btn-danger" onClick={() => removeZone(current.id)}>
                  <Icon name="trash" /> Șterge
                </button>
              </div>
            </div>
          )}
          <section aria-labelledby="zones-h">
            <h2 id="zones-h" className="h3">
              {countZones(zones.length)}
            </h2>
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
                    <span
                      className={`swatch zone-${z.tag}`}
                      role="img"
                      aria-label={tagLabel(z.tag)}
                      title={tagLabel(z.tag)}
                    />
                    <span>{z.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>
      {leaving && (
        <Dialog
          title={`Ai modificări nesalvate pe ${camera.name}`}
          icon="warn"
          onClose={() => setLeaving(null)}
          actions={
            <>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  const go = leaving;
                  setLeaving(null);
                  setDirty(false);
                  go();
                }}
              >
                Renunță la modificări
              </button>
              <button type="button" className="btn" onClick={() => setLeaving(null)} data-autofocus>
                Rămâi
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={saving}
                onClick={async () => {
                  const go = leaving;
                  if (await save()) {
                    setLeaving(null);
                    go();
                  }
                }}
              >
                Salvează și pleacă
              </button>
            </>
          }
        >
          <p className="muted">
            Dacă pleci acum, zonele desenate sau schimbate de la ultima salvare se pierd.
          </p>
        </Dialog>
      )}
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
      <Segmented
        label="Tip"
        value={tag}
        onChange={onTag}
        options={ZONE_TAGS.map((t) => ({
          value: t.value,
          label: t.label,
          swatch: `zone-${t.value}`,
        }))}
      />
    </>
  );
}
