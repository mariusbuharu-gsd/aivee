import { useEffect, useRef, useState } from 'react';
import type { CameraFrame } from '../api/client';
import { useApi } from '../api/context';
import { Icon } from '../components/Icon';
import { useNow } from '../live/useNow';
import { sinceRo } from './lastSeen';

/** A card's still is asked for again at most this often, and only while the card is on screen. */
export const FRAME_REFRESH_MS = 30_000;

/** True once the element is on screen (always true where IntersectionObserver is missing). */
function useOnScreen<T extends Element>(): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [visible, setVisible] = useState(() => typeof IntersectionObserver === 'undefined');
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver((entries) => {
      const e = entries[entries.length - 1];
      if (e) setVisible(e.isIntersecting);
    });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return [ref, visible];
}

/**
 * The camera's newest face-blurred still (`captureFrame`), loaded when the card scrolls into
 * view and refreshed every 30 s while it stays there. A quiet placeholder until one exists or
 * when it fails; a failed refresh keeps the previous still.
 */
export function CameraThumb({
  cameraId,
  name,
  online,
}: {
  cameraId: string;
  name: string;
  online: boolean;
}) {
  const api = useApi();
  const [ref, visible] = useOnScreen<HTMLDivElement>();
  const [frame, setFrame] = useState<CameraFrame | null>(null);
  const [failed, setFailed] = useState(false);
  const lastLoad = useRef(0);
  const now = useNow(frame !== null);

  useEffect(() => {
    if (!visible) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () => {
      lastLoad.current = Date.now();
      api
        .captureFrame(cameraId)
        .then(
          (f) => {
            if (!alive) return f.release();
            setFailed(false);
            setFrame((prev) => {
              prev?.release();
              return f;
            });
          },
          () => alive && setFailed(true),
        )
        .finally(() => {
          if (alive) timer = setTimeout(load, FRAME_REFRESH_MS);
        });
    };
    const wait = lastLoad.current ? lastLoad.current + FRAME_REFRESH_MS - Date.now() : 0;
    timer = setTimeout(load, Math.max(0, wait));
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [api, cameraId, visible]);

  // Free the last blob URL when the card goes away.
  const current = useRef(frame);
  useEffect(() => {
    current.current = frame;
  }, [frame]);
  useEffect(() => () => current.current?.release(), []);

  const at = frame?.at ? Date.parse(frame.at) : NaN;
  return (
    <div ref={ref} className={`device-thumb ${online ? '' : 'is-offline'}`}>
      {frame ? (
        <>
          <img
            src={frame.url}
            alt={`Captură de la ${name}, cu fețele estompate`}
            decoding="async"
            onError={() => {
              frame.release();
              setFrame(null);
              setFailed(true);
            }}
          />
          {!Number.isNaN(at) && (
            <span className="device-thumb-age mono">captură de acum {sinceRo(now - at)}</span>
          )}
        </>
      ) : (
        <span className="device-thumb-empty">
          <Icon name="snapshot" />
          {failed ? 'Nicio captură încă' : <span className="visually-hidden">Se încarcă</span>}
        </span>
      )}
    </div>
  );
}
