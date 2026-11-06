import { useState } from 'react';
import { RuleComposer } from '../components/RuleComposer';
import { describeRule } from '../rules/describe';
import { useLiveData } from '../state/context';

export function RulesPage() {
  const { rules, cameras, addRule } = useLiveData();
  const [cameraId, setCameraId] = useState<string>('');
  const selected = cameraId || cameras[0]?.id || '';
  return (
    <div className="page">
      <header className="page-head">
        <h1>Reguli</h1>
        {cameras.length > 1 && (
          <label className="field-inline">
            <span>Camera</span>
            <select
              className="input"
              value={selected}
              onChange={(e) => setCameraId(e.target.value)}
            >
              {cameras.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>
      {selected && <RuleComposer cameraId={selected} onCreated={addRule} />}
      <section aria-labelledby="rules-h">
        <h2 id="rules-h">Reguli active</h2>
        <ul className="cards">
          {rules.map((r) => (
            <li key={r.id} className="card">
              <div className="side-head">
                <h3>{r.name}</h3>
                <span className={`pill ${r.enabled === false ? 'pill-muted' : 'pill-live'}`}>
                  {r.enabled === false ? 'inactivă' : 'activă'}
                </span>
              </div>
              <p className="muted">„{r.prompt_ro}”</p>
              <p>{describeRule(r)}</p>
              <details>
                <summary>JSON</summary>
                <pre className="mono json">{JSON.stringify(r, null, 2)}</pre>
              </details>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
