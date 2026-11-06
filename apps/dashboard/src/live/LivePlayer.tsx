import { useEffect, useRef, useState } from 'react';
import { startWhep, webRtcSupported, whepUrl } from './whep';

type Status = 'connecting' | 'playing' | 'placeholder';

/**
 * Live camera video over WebRTC (MediaMTX WHEP). Falls back to a placeholder grid when
 * WebRTC is unavailable, the device is offline, or MediaMTX does not answer.
 */
export function LivePlayer({
  cameraId,
  enabled = true,
  label,
}: {
  cameraId: string;
  enabled?: boolean;
  label: string;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canTry = enabled && webRtcSupported();
  const [status, setStatus] = useState<Status>(canTry ? 'connecting' : 'placeholder');

  useEffect(() => {
    if (!canTry) return;
    const ctrl = new AbortController();
    let session: { close: () => void } | null = null;
    let alive = true;
    startWhep(
      whepUrl(cameraId),
      (stream) => {
        if (videoRef.current) videoRef.current.srcObject = stream;
        if (alive) setStatus('playing');
      },
      ctrl.signal,
    )
      .then((s) => {
        if (alive) session = s;
        else s.close();
      })
      .catch(() => alive && setStatus('placeholder'));
    return () => {
      alive = false;
      ctrl.abort();
      session?.close();
    };
  }, [cameraId, canTry]);

  const shown: Status = canTry ? status : 'placeholder';

  return (
    <div className="player" data-status={shown}>
      {shown !== 'placeholder' && (
        <video ref={videoRef} autoPlay muted playsInline aria-label={label} />
      )}
      {shown !== 'playing' && (
        <div className="player-placeholder" role="img" aria-label={`${label}: imagine simulată`}>
          <PlaceholderScene />
        </div>
      )}
    </div>
  );
}

/** A schematic room (floor grid, two tables, a door) so overlays have context without video. */
function PlaceholderScene() {
  return (
    <svg viewBox="0 0 160 90" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <pattern id="grid" width="10" height="10" patternUnits="userSpaceOnUse">
          <path d="M10 0H0V10" fill="none" stroke="#232A31" strokeWidth="0.4" />
        </pattern>
      </defs>
      <rect width="160" height="90" fill="#13181D" />
      <rect width="160" height="90" fill="url(#grid)" />
      <path d="M0 40 L160 34" stroke="#2A333B" strokeWidth="0.6" />
      <rect x="14" y="52" width="38" height="16" rx="3" fill="#1C232A" stroke="#2A333B" />
      <rect x="74" y="52" width="38" height="16" rx="3" fill="#1C232A" stroke="#2A333B" />
      <rect x="128" y="18" width="24" height="38" fill="#1C232A" stroke="#2A333B" />
    </svg>
  );
}
