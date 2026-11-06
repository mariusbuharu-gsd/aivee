import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import type { CameraView, Detection } from '../api/client';
import { useApi } from '../api/context';
import { detectionLabel } from '../live/detections';
import { LivePlayer } from '../live/LivePlayer';
import { toSvgPoints } from '../zones/geometry';
import { Icon } from './Icon';

export function CameraTile({ camera }: { camera: CameraView }) {
  const api = useApi();
  const [detections, setDetections] = useState<Detection[]>([]);

  useEffect(() => {
    if (!camera.online) return;
    return api.subscribeDetections(camera.id, setDetections);
  }, [api, camera.id, camera.online]);

  const shown = camera.online ? detections : [];

  return (
    <article className="tile" aria-label={`Camera ${camera.name}`}>
      <div className="tile-media">
        <LivePlayer cameraId={camera.id} enabled={camera.online} label={camera.name} />
        {camera.online ? (
          <svg className="overlay" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">
            {(camera.zones ?? []).map((z) => (
              <polygon key={z.id} className="zone-outline" points={toSvgPoints(z.polygon)} />
            ))}
          </svg>
        ) : (
          <div className="tile-offline" role="status">
            <Icon name="offline" size={28} />
            <span>Dispozitiv offline</span>
            <span className="muted mono">{camera.device}</span>
          </div>
        )}
        {shown.map((d) => (
          <div
            key={d.track_id}
            className={`det det-${d.role}${d.raised_hand ? ' det-hand' : ''}`}
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
        <span className={`badge ${camera.online ? 'badge-live' : 'badge-off'}`}>
          {camera.online ? 'LIVE' : 'OFFLINE'}
        </span>
      </div>
      <footer className="tile-foot">
        <div className="tile-title">
          <span>{camera.name}</span>
          <span className="muted mono small">
            {camera.zones?.length ?? 0} zone · {shown.length} persoane
          </span>
        </div>
        <Link
          to={`/camere/${encodeURIComponent(camera.id)}/zone`}
          className="btn btn-ghost"
          aria-label={`Editează zonele pentru ${camera.name}`}
        >
          <Icon name="edit" /> Zone
        </Link>
      </footer>
    </article>
  );
}
