import { useEffect, useState } from 'react';
import { useApi } from '../api/context';
import { RuleComposer, RuleDraftEditor } from '../components/RuleComposer';
import type { Rule } from '../contracts';
import { useAuth } from '../auth/context';
import { shortRule } from '../rules/chips';
import { defaultCamera } from '../devices/defaultCamera';
import { describeRule } from '../rules/describe';
import { RuleSparkline } from '../rules/RuleSparkline';
import { ruleTemplates } from '../rules/templates';
import { useLiveData } from '../state/context';
import { Banner } from '../ui/Banner';
import { ConfirmDialog, Dialog } from '../ui/Dialog';
import { Menu } from '../ui/Menu';
import { Select } from '../ui/Select';
import { EmptyState, Switch } from '../ui/controls';
import { useToast } from '../ui/toast';
import './RulesPage.css';
import { BusyLabel } from '../ui/Eyes';

export function RulesPage() {
  const api = useApi();
  const { rules, cameras, addRule } = useLiveData();
  const { location } = useAuth();
  const [cameraId, setCameraId] = useState<string>('');
  const [stats, setStats] = useState<Map<string, number[]>>(new Map());
  useEffect(() => {
    let live = true;
    api.getRuleStats(7).then(
      (s) => live && setStats(new Map(s.rules.map((r) => [r.rule_id, r.per_day]))),
      () => live && setStats(new Map()), // the cards just show no sparkline
    );
    return () => {
      live = false;
    };
  }, [api, location?.id]);
  const selected = cameraId || defaultCamera(cameras, rules)?.id || '';
  const picker =
    cameras.length > 1 ? (
      <Select
        size="sm"
        className="composer-camera"
        label="pentru camera"
        value={selected}
        options={cameras.map((c) => ({ value: c.id, label: c.name }))}
        onChange={setCameraId}
      />
    ) : undefined;
  const groups = cameras
    .map((c) => ({ camera: c, rules: rules.filter((r) => r.camera_id === c.id) }))
    .filter((g) => g.rules.length > 0);
  const orphans = rules.filter((r) => !cameras.some((c) => c.id === r.camera_id));
  return (
    <div className="page">
      <header className="page-head">
        <h1>Reguli</h1>
      </header>
      {selected && (
        <RuleComposer
          cameraId={selected}
          onCreated={addRule}
          camera={picker}
          examples={ruleTemplates(location?.type)}
          startHere={!rules.some((r) => r.camera_id === selected)}
        />
      )}
      <section aria-labelledby="rules-h" className="rule-groups">
        <h2 id="rules-h">Regulile tale</h2>
        {rules.length === 0 && (
          <EmptyState icon="rules" title="Nicio regulă încă">
            Scrie mai sus, în română, ce să urmărească, sau pornește de la unul dintre exemple.
          </EmptyState>
        )}
        {groups.map((g) => (
          <div key={g.camera.id}>
            {cameras.length > 1 && <h3 className="feed-group">{g.camera.name}</h3>}
            <RuleList rules={g.rules} stats={stats} />
          </div>
        ))}
        {orphans.length > 0 && <RuleList rules={orphans} stats={stats} />}
      </section>
    </div>
  );
}

function RuleList({ rules, stats }: { rules: Rule[]; stats: Map<string, number[]> }) {
  return (
    <ul className="cards">
      {rules.map((r) => (
        <RuleCard key={r.id} rule={r} perDay={stats.get(r.id)} />
      ))}
    </ul>
  );
}

function RuleCard({ rule, perDay }: { rule: Rule; perDay?: number[] }) {
  const api = useApi();
  const toast = useToast();
  const { addRule, removeRule } = useLiveData();
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<'edit' | 'delete' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const on = rule.enabled !== false;

  async function setEnabled(enabled: boolean, undo = true) {
    setBusy(true);
    setError(null);
    try {
      addRule(await api.updateRule(rule.id, { enabled }));
      toast({
        kind: enabled ? 'ok' : 'info',
        title: enabled ? `„${rule.name}” a pornit` : `„${rule.name}” e oprită`,
        text: enabled ? 'Alertele vin din nou.' : 'Nu mai trimite alerte până o pornești.',
        action: undo ? { label: 'Anulează', run: () => setEnabled(!enabled, false) } : undefined,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Nu am putut schimba regula.');
    } finally {
      setBusy(false);
    }
  }

  async function duplicate() {
    try {
      const copy = await api.createRule({
        ...rule,
        id: `${rule.id}-copie-${Date.now().toString(36)}`,
        name: `${rule.name} (copie)`,
        enabled: false,
      });
      addRule(copy);
      toast({ title: `Am făcut „${copy.name}”`, text: 'E oprită; pornește-o când e gata.' });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Nu am putut copia regula.');
    }
  }

  return (
    <li className={`card rule-card ${on ? '' : 'is-off'}`}>
      <div className="side-head">
        <div className="rule-title">
          <h3>{rule.name}</h3>
          <span className={`pill ${on ? 'pill-ok' : 'pill-muted'}`}>
            {on ? 'activă' : 'oprită'}
          </span>
        </div>
        <div className="rule-tools">
          <Switch
            checked={on}
            disabled={busy}
            label={<span className="visually-hidden">Regula {rule.name} e activă</span>}
            onChange={(v) => void setEnabled(v)}
          />
          <Menu
            label={`Acțiuni pentru regula ${rule.name}`}
            items={[
              { label: 'Modifică', onSelect: () => setDialog('edit') },
              { label: 'Duplică', onSelect: () => void duplicate() },
              { label: 'Șterge regula…', danger: true, onSelect: () => setDialog('delete') },
            ]}
          />
        </div>
      </div>
      <p className="rule-line">{shortRule(rule)}</p>
      {rule.prompt_ro && <p className="muted small rule-prompt">„{rule.prompt_ro}”</p>}
      {perDay && <RuleSparkline perDay={perDay} />}
      {error && <Banner tone="error" title={error} />}
      <details className="tech">
        <summary>Detalii</summary>
        <p className="small">{describeRule(rule)}</p>
        <pre className="mono json">{JSON.stringify(rule, null, 2)}</pre>
      </details>
      {dialog === 'delete' && (
        <ConfirmDialog
          title={`Ștergi regula „${rule.name}”?`}
          confirmLabel="Șterge regula"
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            await api.deleteRule(rule.id);
            removeRule(rule.id);
            toast({ title: `Regula „${rule.name}” a fost ștearsă` });
          }}
        >
          <ul>
            <li>Dispozitivul nu mai trimite alerte pentru ea, de acum.</li>
            <li>Alertele vechi rămân în Istoric.</li>
            <li>Dacă vrei doar o pauză, oprește-o din comutator.</li>
          </ul>
        </ConfirmDialog>
      )}
      {dialog === 'edit' && <EditRule rule={rule} onClose={() => setDialog(null)} />}
    </li>
  );
}

function EditRule({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  const api = useApi();
  const toast = useToast();
  const { addRule } = useLiveData();
  const [draft, setDraft] = useState(rule);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!draft.name.trim()) return setError('Regula are nevoie de un nume.');
    setBusy(true);
    setError(null);
    try {
      addRule(
        await api.updateRule(rule.id, {
          name: draft.name.trim(),
          all_of: draft.all_of,
          cooldown_s: draft.cooldown_s,
        }),
      );
      toast({
        title: `„${draft.name.trim()}” a fost salvată`,
        text: 'Dispozitivul are noua versiune.',
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Nu am putut salva regula.');
      setBusy(false);
    }
  }

  return (
    <Dialog
      title={`Modifici „${rule.name}”`}
      icon="edit"
      onClose={() => !busy && onClose()}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy} data-autofocus>
            Renunță
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void save()}
            disabled={busy}
          >
            <BusyLabel busy={busy} idle="Salvează">
              Se salvează…
            </BusyLabel>
          </button>
        </>
      }
    >
      <p className="muted small">{describeRule(draft)}</p>
      <RuleDraftEditor rule={draft} onChange={setDraft} />
      {error && <Banner tone="error" title={error} />}
    </Dialog>
  );
}
