import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import type { CameraView, Detection } from '../api/client';
import { useApi } from '../api/context';
import { useAuth } from '../auth/context';
import { detectionLabel, detectionTitle } from '../live/detections';
import { plural } from '../ui/plural';
import { LivePlayer } from '../live/LivePlayer';
import { isCloudFrames } from '../live/source';
import { toSvgPoints } from '../zones/geometry';
import { Icon } from './Icon';
import './live.css';

/**
 * One camera on Live. `hot` marks zones with an open alert (zone id → timer text): the zone is
 * outlined in coral with the time on it, so the owner sees where, not only that. An offline
 * camera collapses to one row: what is down and where to look.
 */
export function CameraTile({
  camera,
  hot = {},
}: {
  camera: CameraView;
  hot?: Record<string, string>;
}) {
  const api = useApi();
  const { can } = useAuth();
  const [detections, setDetections] = useState<Detection[]>([]);

  useEffect(() => {
    if (!camera.online) return;
    return api.subscribeDetections(camera.id, setDetections);
  }, [api, camera.id, camera.online]);

  const shown = camera.online ? detections : [];

  if (!camera.online) {
    return (
      <article className="tile tile-down" aria-label={`Camera ${camera.name}`}>
        <span className="badge badge-off">OFFLINE</span>
        <div className="tile-down-text">
          <strong>{camera.name}</strong>
          <span className="tile-down-what">
            <span>Dispozitiv offline</span>
            <span className="mono">{camera.device}</span>
          </span>
          <span className="muted small">Alertele de la această cameră nu vin până revine.</span>
        </div>
        {can('devices.manage') && (
          <Link to="/dispozitive" className="link">
            Ce să verific
          </Link>
        )}
      </article>
    );
  }

  return (
    <article className="tile" aria-label={`Camera ${camera.name}`}>
      <div className="tile-media">
        <LivePlayer
          cameraId={camera.id}
          enabled
          label={camera.name}
          mjpegUrl={api.liveMjpegUrl(camera.id)}
          cloudFrames={isCloudFrames(camera.source)}
        />
        <svg className="overlay" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">
          {(camera.zones ?? []).map((z) => (
            <polygon
              key={z.id}
              className={`zone-outline${hot[z.id] ? ' zone-hot' : ''}`}
              points={toSvgPoints(z.polygon)}
            />
          ))}
        </svg>
        {(camera.zones ?? [])
          .filter((z) => hot[z.id])
          .map((z) => {
            const xs = z.polygon.map((p) => p[0]);
            const ys = z.polygon.map((p) => p[1]);
            return (
              <span
                key={z.id}
                className="zone-hot-label mono"
                style={{ left: `${Math.min(...xs) * 100}%`, top: `${Math.max(...ys) * 100}%` }}
              >
                {z.name} · {hot[z.id]}
              </span>
            );
          })}
        {shown.map((d) => (
          <div
            key={d.track_id}
            className={`det det-${d.role}${d.raised_hand ? ' det-hand' : ''}`}
            title={detectionTitle(d)}
            style={{
              left: `${d.box[0] * 100}%`,
              top: `${d.box[1] * 100}%`,
              width: `${d.box[2] * 100}%`,
              height: `${d.box[3] * 100}%`,
            }}
          >
            <span className="det-label mono">{detectionLabel(d)}</span>
          </div>
        ))}
        <span className="badge badge-live">LIVE</span>
      </div>
      <footer className="tile-foot">
        <div className="tile-title">
          <span>{camera.name}</span>
          <span className="muted mono small">
            {plural(camera.zones?.length ?? 0, 'zonă', 'zone')} ·{' '}
            {plural(shown.length, 'persoană', 'persoane')}
          </span>
        </div>
        {can('devices.manage') && (
          <Link
            to={`/camere/${encodeURIComponent(camera.id)}/zone`}
            className="btn btn-ghost"
            aria-label={`Editează zonele pentru ${camera.name}`}
          >
            <Icon name="edit" /> Zone
          </Link>
        )}
      </footer>
    </article>
  );
}
