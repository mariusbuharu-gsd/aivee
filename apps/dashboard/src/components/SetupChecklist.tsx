import { useEffect, useId, useMemo, useState } from 'react';
import { Link } from 'react-router';
import type { StaffProfile } from '../api/client';
import { useApi } from '../api/context';
import { useAuth } from '../auth/context';
import { browserPushService, type PushService } from '../push/service';
import {
  isSetupHidden,
  isTestSent,
  markTestSent,
  progressLabel,
  setSetupHidden,
  setupProgress,
  setupSteps,
  showSetup,
  type SetupStep,
} from '../setup/checklist';
import { useLiveData } from '../state/context';
import { Banner } from '../ui/Banner';
import { useToast } from '../ui/toast';
import { Icon } from './Icon';

interface Extra {
  profiles: StaffProfile[] | null;
  telegram: boolean;
  pushOn: boolean;
}

/** "Configurare" card on Live: what is left before the first real alert. Owners and managers. */
export function SetupChecklist({ push: pushProp }: { push?: PushService }) {
  const api = useApi();
  const toast = useToast();
  const { me, location, can } = useAuth();
  const { cameras, rules, loading } = useLiveData();
  const push = useMemo(() => pushProp ?? browserPushService(), [pushProp]);
  const userId = me?.user.id ?? '';
  const locationId = location?.id ?? null;
  const canEnrol = can('staff.enrol');
  const headingId = useId();
  const listId = useId();
  const [extra, setExtra] = useState<Extra | null>(null);
  const [hidden, setHidden] = useState(() => isSetupHidden(userId));
  const [tested, setTested] = useState(() => isTestSent(userId));
  const [open, setOpen] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const profiles = canEnrol
      ? api.listStaffProfiles().catch(() => null)
      : Promise.resolve<StaffProfile[] | null>(null);
    const telegram = api
      .listLocations()
      .then((ls) => !!ls.find((l) => l.id === locationId)?.telegram_chat_id)
      .catch(() => false);
    const pushOn = push.state().then(
      (s) => s === 'on',
      () => false,
    );
    void Promise.all([profiles, telegram, pushOn]).then(([p, t, on]) => {
      if (alive) setExtra({ profiles: p, telegram: t, pushOn: on });
    });
    return () => {
      alive = false;
    };
  }, [api, push, canEnrol, locationId]);

  if (hidden || loading || !extra) return null;
  const steps = setupSteps({
    hasLocation: !!location,
    cameras,
    rules,
    staffProfiles: extra.profiles,
    pushOn: extra.pushOn,
    telegram: extra.telegram,
    testSent: tested,
    can,
  });
  if (!showSetup(location?.role, steps)) return null;
  const { done, total } = setupProgress(steps);

  function hide() {
    setSetupHidden(userId, true);
    setHidden(true);
    toast({
      kind: 'info',
      title: 'Am ascuns ghidul de configurare',
      action: {
        label: 'Anulează',
        run: () => {
          setSetupHidden(userId, false);
          setHidden(false);
        },
      },
    });
  }

  async function sendTest() {
    setBusy(true);
    setError(null);
    try {
      const r = await push.sendTest();
      if (r.sent > 0) {
        markTestSent(userId);
        setTested(true);
        toast({ title: 'Am trimis o alertă de test', text: 'Uită-te pe telefon.' });
      } else {
        setError('Niciun dispozitiv abonat nu a primit testul. Pornește notificările din nou.');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Nu am putut trimite testul.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card setup" aria-labelledby={headingId}>
      <div className="setup-head">
        <div className="setup-title">
          <h2 id={headingId}>Configurare</h2>
          <span className="mono small muted" data-testid="setup-progress">
            {progressLabel(steps)}
          </span>
        </div>
        <div className="setup-tools">
          <button
            type="button"
            className="btn btn-ghost"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? 'Restrânge' : 'Arată pașii'}
          </button>
          <button type="button" className="btn btn-ghost" onClick={hide}>
            Ascunde
          </button>
        </div>
      </div>
      <div
        className="setup-bar"
        role="progressbar"
        aria-label="Pași făcuți"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        aria-valuetext={progressLabel(steps)}
      >
        <span style={{ width: `${(done / total) * 100}%` }} />
      </div>
      {open && (
        <ol id={listId} className="setup-steps">
          {steps.map((s) => (
            <StepRow key={s.id} step={s} busy={busy} onTest={() => void sendTest()} />
          ))}
        </ol>
      )}
      {error && <Banner tone="error" title={error} />}
    </section>
  );
}

function StepRow({ step, busy, onTest }: { step: SetupStep; busy: boolean; onTest: () => void }) {
  return (
    <li className={`setup-step ${step.done ? 'is-done' : ''}`} data-step={step.id}>
      <span className="setup-mark" aria-hidden="true">
        {step.done ? <Icon name="checkCircle" /> : <span className="setup-dot" />}
      </span>
      <div className="setup-body">
        <strong>
          {step.title}
          <span className="visually-hidden">{step.done ? ' — gata' : ' — de făcut'}</span>
        </strong>
        {!step.done && <span className="muted small">{step.text}</span>}
        {!step.done && step.waitingFor && !step.blocked && (
          <span className="small setup-wait">{step.waitingFor}</span>
        )}
      </div>
      {!step.done && <StepAction step={step} busy={busy} onTest={onTest} />}
    </li>
  );
}

function StepAction({
  step,
  busy,
  onTest,
}: {
  step: SetupStep;
  busy: boolean;
  onTest: () => void;
}) {
  if (step.blocked) return <span className="pill pill-muted setup-ask">cere-i proprietarului</span>;
  if (step.to === null) {
    return (
      <button
        type="button"
        className="btn setup-action"
        disabled={busy || !!step.waitingFor}
        onClick={onTest}
      >
        {busy ? 'Se trimite…' : step.action}
      </button>
    );
  }
  if (step.waitingFor) {
    return (
      <button type="button" className="btn setup-action" disabled>
        {step.action}
      </button>
    );
  }
  return (
    <Link to={step.to} className="btn setup-action">
      {step.action}
    </Link>
  );
}
