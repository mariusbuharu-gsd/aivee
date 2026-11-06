import { MetricsStrip } from '../components/MetricsStrip';
import { ServiceStats } from '../components/ServiceStats';
import { useLiveData } from '../state/context';

export function MetricsPage() {
  const { metrics } = useLiveData();
  return (
    <div className="page">
      <header className="page-head">
        <h1>Metrici</h1>
      </header>
      <ServiceStats />
      <MetricsStrip metrics={metrics} />
      <section aria-labelledby="per-device-h">
        <h2 id="per-device-h">Pe dispozitiv</h2>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Dispozitiv</th>
                <th scope="col">FPS</th>
                <th scope="col">Cadre verificate</th>
                <th scope="col">CPU</th>
              </tr>
            </thead>
            <tbody>
              {(metrics?.devices ?? []).map((d) => (
                <tr key={d.device}>
                  <th scope="row" className="mono">
                    {d.device}
                  </th>
                  <td className="mono">{d.fps.toFixed(1)}</td>
                  <td className="mono">{(d.verified_ratio * 100).toFixed(1)}%</td>
                  <td className="mono">{Math.round(d.cpu_percent)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">
          Cadre verificate = procentul de cadre trimise modelului greu. Restul rulează doar detecția
          rapidă, pe dispozitiv.
        </p>
      </section>
    </div>
  );
}
