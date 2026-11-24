import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { ApiError, type CameraView, type DiscoveredCamera } from '../api/client';
import { useApi } from '../api/context';
import { cameraProblem, problemHint, type CameraProblem } from '../devices/cameraProblems';
import {
  cameraIdFor,
  defaultUser,
  discoveredSource,
  discoveredTitle,
  onlineBoxes,
  type BoxChoice,
} from '../devices/discovery';
import { useCameraTest } from '../devices/useCameraTest';
import { useCapabilities } from '../state/capabilitiesContext';
import { Banner } from '../ui/Banner';
import { BusyLabel } from '../ui/Eyes';
import { PasswordInput, Skeleton } from '../ui/controls';
import { plural } from '../ui/plural';
import { AddCameraForm, DEFAULT_CAMERA_ID, DEFAULT_DEVICE } from './AddCameraForm';
import { CameraTestOutcome } from './CameraTestOutcome';
import { Icon } from './Icon';
import { TapoGuide } from './TapoGuide';
import './CameraSetup.css';

interface AddCameraProps {
  /** The location's cameras: taken ids, and which box already serves which camera. */
  cameras: CameraView[];
  onCreated: (camera: CameraView) => void;
  onCancel?: () => void;
  /** For the manual form: the next free id and the box of the other cameras. */
  defaultId?: string;
  defaultDevice?: string;
}

/**
 * "Adaugă cameră". When the server can look for cameras, the owner goes through the wizard
 * (box → "Caută camere" → account → name → zones) and never types an IP; "Adaug-o manual"
 * switches to the brand + IP form, which also covers phones and raw sources.
 */
export function AddCamera({
  cameras,
  onCreated,
  onCancel,
  defaultId = DEFAULT_CAMERA_ID,
  defaultDevice = DEFAULT_DEVICE,
}: AddCameraProps) {
  const caps = useCapabilities();
  const [manual, setManual] = useState<{ device: string | null } | null>(null);
  const form = (device: string) => (
    <AddCameraForm
      defaultId={defaultId}
      defaultDevice={device}
      onCreated={onCreated}
      onCancel={onCancel}
    />
  );
  if (!caps?.camera_discovery) return form(defaultDevice);
  if (manual) {
    return (
      <div className="wizard-manual">
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setManual(null)}>
          <Icon name="undo" size={16} /> Înapoi la „Caută camere”
        </button>
        {form(manual.device ?? defaultDevice)}
      </div>
    );
  }
  return (
    <AddCameraWizard
      cameras={cameras}
      onCreated={onCreated}
      onCancel={onCancel}
      onManual={(device) => setManual({ device })}
    />
  );
}

type Step = 'box' | 'find' | 'account' | 'name';

const STEPS: { step: Step | 'zones'; label: string }[] = [
  { step: 'box', label: 'Cutia' },
  { step: 'find', label: 'Camera' },
  { step: 'account', label: 'Contul' },
  { step: 'name', label: 'Numele' },
  { step: 'zones', label: 'Zonele' },
];

const NAME_IDEAS = ['Sala mare', 'Bar', 'Terasă', 'Intrare'];

function AddCameraWizard({
  cameras,
  onCreated,
  onCancel,
  onManual,
}: {
  cameras: CameraView[];
  onCreated: (camera: CameraView) => void;
  onCancel?: () => void;
  onManual: (device: string | null) => void;
}) {
  const api = useApi();
  const caps = useCapabilities();
  const canTest = !!caps?.camera_test;
  const [step, setStep] = useState<Step>('box');
  const [boxes, setBoxes] = useState<BoxChoice[] | null>(null);
  const [boxError, setBoxError] = useState<string | null>(null);
  const [device, setDevice] = useState<string | null>(null);
  const [found, setFound] = useState<DiscoveredCamera[] | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanProblem, setScanProblem] = useState<CameraProblem | null>(null);
  const [picked, setPicked] = useState<DiscoveredCamera | null>(null);
  const [user, setUser] = useState('');
  const [password, setPassword] = useState('');
  const [guideOpen, setGuideOpen] = useState(false);
  const [name, setName] = useState('');
  const [nameError, setNameError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const test = useCameraTest();
  const resetTest = test.reset;

  // Asked on open and by "Verifică din nou" (which first clears the state).
  const loadBoxes = useCallback(
    () =>
      api.listDevices().then(
        (list) => {
          const choices = onlineBoxes(list, cameras);
          setBoxError(null);
          setBoxes(choices);
          // One box, the usual case: nothing to choose.
          if (choices.length === 1) {
            setDevice(choices[0]?.device ?? null);
            setStep('find');
          }
        },
        (e: unknown) => {
          setBoxes([]);
          setBoxError(e instanceof Error ? e.message : 'Nu am putut întreba de cutia AiVee.');
        },
      ),
    // `cameras` only labels the boxes; asking again when it changes would undo a choice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [api],
  );

  useEffect(() => {
    void loadBoxes();
  }, [loadBoxes]);

  function checkAgain() {
    setBoxes(null);
    setBoxError(null);
    void loadBoxes();
  }

  async function scan() {
    if (!device) return;
    setScanning(true);
    setScanProblem(null);
    try {
      setFound(await api.discoverCameras(device));
    } catch (e) {
      setFound(null);
      setScanProblem(cameraProblem(e));
    } finally {
      setScanning(false);
    }
  }

  function pick(c: DiscoveredCamera) {
    setPicked(c);
    setUser(defaultUser(c.brand));
    setPassword('');
    setGuideOpen(false);
    resetTest();
    setStep('account');
  }

  const source = picked ? discoveredSource(picked, user.trim(), password) : '';
  const tapo = picked?.brand === 'tapo';
  const tested = test.key === source;
  const testedOk = tested && !!test.frame;
  const boxProblem =
    tested && (test.problem?.code === 'device_offline' || test.problem?.code === 'device_timeout');

  async function runTest() {
    if (!picked || !device) return;
    const problem = await test.run({ source, device }, source);
    // A refused password on a Tapo is almost always the Tapo account: show how to make one.
    if (problem?.code === 'camera_auth' && tapo) setGuideOpen(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    const n = name.trim();
    if (!n) return setNameError('Scrie un nume, de exemplu „Sala mare” sau „Bar”.');
    if (!picked || !device || saving) return;
    setNameError(null);
    setSaving(true);
    setSaveError(null);
    const taken = cameras.map((c) => c.id);
    let id = cameraIdFor(n, taken);
    try {
      let created: CameraView;
      try {
        created = await api.createCamera({ id, name: n, source, device });
      } catch (err) {
        // Someone else took the id meanwhile: one more go with the next free one.
        if (!(err instanceof ApiError) || err.status !== 409) throw err;
        id = cameraIdFor(n, [...taken, id]);
        created = await api.createCamera({ id, name: n, source, device });
      }
      onCreated(created);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Nu am putut salva camera.');
      setSaving(false);
    }
  }

  const several = (boxes?.length ?? 0) > 1;
  const current = STEPS.findIndex((s) => s.step === step);

  return (
    <div className="wizard">
      <ol className="wizard-steps" aria-label="Pașii">
        {STEPS.map((s, i) => (
          <li
            key={s.step}
            className={i < current ? 'is-done' : i === current ? 'is-current' : undefined}
            aria-current={i === current ? 'step' : undefined}
          >
            <span className="wizard-step-n mono">{i + 1}</span>{' '}
            <span className="wizard-step-label">{s.label}</span>
          </li>
        ))}
      </ol>

      {step === 'box' && (
        <section className="wizard-pane" aria-labelledby="wz-box">
          {boxes === null ? (
            <Skeleton rows={1} label="Caut cutia AiVee" />
          ) : boxError ? (
            <>
              <h3 id="wz-box" className="h3">
                Nu am putut vorbi cu serverul
              </h3>
              <Banner tone="error" title="Nu știm încă dacă cutia AiVee e pornită.">
                {boxError}
              </Banner>
              <div className="row-actions">
                <button type="button" className="btn" onClick={checkAgain}>
                  Încearcă din nou
                </button>
              </div>
            </>
          ) : boxes.length === 0 ? (
            <div className="wizard-empty">
              <span className="empty-icon" aria-hidden="true">
                <Icon name="offline" size={22} />
              </span>
              <h3 id="wz-box" className="h3">
                Cutia AiVee nu e pornită sau nu e conectată
              </h3>
              <p className="muted small">Cutia caută camerele din local. Verifică, în ordine:</p>
              <ol className="wizard-checks">
                <li>Cutia AiVee e în priză și are lumina aprinsă.</li>
                <li>Cablul de rețea e băgat în cutie și în routerul localului.</li>
                <li>Camerele sunt la același router (aceeași rețea Wi-Fi) cu cutia.</li>
                <li>După ce o pornești, așteaptă un minut.</li>
              </ol>
              <div className="row-actions">
                <button type="button" className="btn btn-primary" onClick={checkAgain}>
                  Verifică din nou
                </button>
                {onCancel && (
                  <button type="button" className="btn btn-ghost" onClick={onCancel}>
                    Renunță
                  </button>
                )}
              </div>
            </div>
          ) : (
            <>
              <h3 id="wz-box" className="h3">
                Ce cutie AiVee caută camerele?
              </h3>
              <p className="muted small">Alege cutia din aceeași rețea cu camera nouă.</p>
              <ul className="wizard-list">
                {boxes.map((b) => (
                  <li key={b.device}>
                    <button
                      type="button"
                      className="wizard-choice"
                      onClick={() => {
                        setDevice(b.device);
                        setFound(null);
                        setScanProblem(null);
                        setStep('find');
                      }}
                    >
                      <span className="wizard-choice-text">
                        <span className="wizard-choice-main">{b.label}</span>
                        <span className="wizard-choice-sub">{b.detail}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      {step === 'find' && (
        <section className="wizard-pane" aria-labelledby="wz-find">
          <h3 id="wz-find" className="h3">
            Caută camerele din local
          </h3>
          {!found && !scanning && !scanProblem && (
            <p className="muted small">
              Cutia AiVee caută camerele conectate la același router. Nu trebuie să știi nimic
              despre ele.
            </p>
          )}
          {scanning ? (
            <div className="scan-progress">
              <div
                className="scan-bar"
                role="progressbar"
                aria-label="Caut camere"
                aria-valuetext="Caut camere în rețeaua localului"
              >
                <span />
              </div>
              <p className="small" role="status">
                Caut camere în rețeaua localului… durează până la 10 secunde.
              </p>
            </div>
          ) : (
            <div className="row-actions">
              <button
                type="button"
                className={found || scanProblem ? 'btn' : 'btn btn-primary'}
                onClick={() => void scan()}
              >
                <Icon name="devices" size={18} />{' '}
                {found || scanProblem ? 'Caută din nou' : 'Caută camere'}
              </button>
            </div>
          )}

          {scanProblem && !scanning && (
            <Banner tone="error" title="Nu am putut căuta camerele.">
              {scanProblem.message}
              {problemHint(scanProblem.code) && (
                <span className="camera-problem-hint">{problemHint(scanProblem.code)}</span>
              )}
            </Banner>
          )}

          {found && !scanning && <FoundList found={found} onPick={pick} />}

          <p className="small wizard-manual-link">
            Nu-mi găsești camera?{' '}
            <button type="button" className="link link-button" onClick={() => onManual(device)}>
              Adaug-o manual
            </button>
          </p>
          {several && (
            <div className="row-actions">
              <button type="button" className="btn btn-ghost" onClick={() => setStep('box')}>
                Înapoi
              </button>
            </div>
          )}
        </section>
      )}

      {step === 'account' && picked && (
        <section className="wizard-pane" aria-labelledby="wz-account">
          <h3 id="wz-account" className="h3">
            Contul camerei
          </h3>
          <PickedCamera camera={picked} />
          {tapo ? (
            <TapoGuide open={guideOpen} onToggle={setGuideOpen} />
          ) : (
            <p className="muted small">Folosește utilizatorul și parola de admin ale camerei.</p>
          )}
          <div className="field-pair">
            <div className="field">
              <label htmlFor="wz-user">Utilizator</label>
              <input
                id="wz-user"
                className="input"
                value={user}
                autoComplete="off"
                spellCheck={false}
                onChange={(e) => setUser(e.target.value)}
              />
            </div>
            <PasswordInput
              id="wz-password"
              label="Parolă"
              value={password}
              autoComplete="new-password"
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {canTest && (
            <div className="camera-test">
              <button
                type="button"
                className={testedOk ? 'btn' : 'btn btn-primary'}
                onClick={() => void runTest()}
                disabled={test.busy || !user.trim() || !password}
                title={user.trim() && password ? undefined : 'Scrie utilizatorul și parola'}
              >
                <BusyLabel busy={test.busy} idle="Testează">
                  Se testează…
                </BusyLabel>
              </button>
              {tested && !test.busy && (
                <CameraTestOutcome frame={test.frame} problem={test.problem} tapo={tapo} />
              )}
            </div>
          )}
          <div className="row-actions">
            <button type="button" className="btn btn-ghost" onClick={() => setStep('find')}>
              Înapoi
            </button>
            {(testedOk || (!canTest && user.trim() && password)) && (
              <button type="button" className="btn btn-primary" onClick={() => setStep('name')}>
                Continuă
              </button>
            )}
            {boxProblem && (
              <button type="button" className="btn" onClick={() => setStep('name')}>
                Continuă fără test
              </button>
            )}
          </div>
        </section>
      )}

      {step === 'name' && picked && (
        <form className="wizard-pane" aria-labelledby="wz-name" onSubmit={save} noValidate>
          <h3 id="wz-name" className="h3">
            Cum îi spui camerei?
          </h3>
          {testedOk && test.frame && (
            <img
              className="wizard-still"
              src={test.frame.url}
              alt="Imaginea de test a camerei, cu fețele estompate"
            />
          )}
          <div className="field">
            <label htmlFor="wz-camera-name">Numele camerei</label>
            <input
              id="wz-camera-name"
              className="input"
              value={name}
              placeholder="ex. Sala mare"
              autoComplete="off"
              data-autofocus
              onChange={(e) => setName(e.target.value)}
              aria-invalid={nameError ? true : undefined}
              aria-describedby={nameError ? 'wz-name-err' : 'wz-name-help'}
            />
            {nameError ? (
              <small id="wz-name-err" className="field-error">
                {nameError}
              </small>
            ) : (
              <small id="wz-name-help" className="muted small">
                Așa o vezi pe Live și în alerte.
              </small>
            )}
          </div>
          <div className="name-ideas" role="group" aria-label="Idei de nume">
            {NAME_IDEAS.map((idea) => (
              <button
                key={idea}
                type="button"
                className="btn btn-sm"
                aria-pressed={name === idea}
                onClick={() => setName(idea)}
              >
                {idea}
              </button>
            ))}
          </div>
          {saveError && (
            <Banner tone="error" title="Camera nu a fost salvată.">
              {saveError}
            </Banner>
          )}
          <div className="row-actions">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setStep('account')}
              disabled={saving}
            >
              Înapoi
            </button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              <BusyLabel busy={saving} idle="Salvează camera">
                Se salvează…
              </BusyLabel>
            </button>
          </div>
          <p className="muted small">Apoi desenezi mesele și intrarea pe imaginea ei.</p>
        </form>
      )}
    </div>
  );
}

/** The cameras the box found; one already in use is greyed out. */
function FoundList({
  found,
  onPick,
}: {
  found: DiscoveredCamera[];
  onPick: (c: DiscoveredCamera) => void;
}) {
  if (found.length === 0) {
    return (
      <div className="wizard-none" role="status">
        <strong>Nu am găsit nicio cameră.</strong>
        <ul className="wizard-checks">
          <li>Camera are curent și a pornit de cel puțin un minut?</li>
          <li>E conectată la același router (aceeași rețea Wi-Fi) cu cutia AiVee?</li>
        </ul>
      </div>
    );
  }
  const free = found.filter((c) => !c.already_added).length;
  return (
    <>
      <p className="small" role="status">
        Am găsit {plural(found.length, 'cameră', 'camere')}
        {free < found.length ? `, ${free} de adăugat` : ''}. Alege-o pe cea nouă.
      </p>
      <ul className="wizard-list" aria-label="Camere găsite">
        {found.map((c) => (
          <li key={`${c.ip}:${c.port}`}>
            <button
              type="button"
              className={`wizard-choice${c.already_added ? ' is-added' : ''}`}
              disabled={c.already_added}
              onClick={() => onPick(c)}
            >
              <span className="wizard-choice-icon" aria-hidden="true">
                <Icon name="snapshot" size={20} />
              </span>
              <span className="wizard-choice-text">
                <span className="wizard-choice-main">{discoveredTitle(c)}</span>
                <span className="wizard-choice-sub">
                  {c.name && <>„{c.name}” · </>}
                  <span className="mono">{c.ip}</span>
                </span>
              </span>
              {c.already_added && <span className="pill pill-muted">Deja adăugată</span>}
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

function PickedCamera({ camera }: { camera: DiscoveredCamera }) {
  return (
    <p className="picked-camera">
      <Icon name="snapshot" size={18} />
      <span>
        <strong>{discoveredTitle(camera)}</strong>
        {camera.name && <> „{camera.name}”</>} · <span className="mono">{camera.ip}</span>
      </span>
    </p>
  );
}
