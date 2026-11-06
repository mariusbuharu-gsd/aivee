import { useEffect, useRef, useState } from 'react';
import { startWhep, webRtcSupported, whepUrl } from './whep';

export type PlayerStatus = 'connecting' | 'playing' | 'placeholder';
type Status = PlayerStatus;

/**
 * Live camera video over WebRTC (MediaMTX WHEP). Falls back to a placeholder grid when
 * WebRTC is unavailable, the device is offline, or MediaMTX does not answer.
 */
export function LivePlayer({
  cameraId,
  enabled = true,
  label,
  onStatus,
  onFrameSize,
}: {
  cameraId: string;
  enabled?: boolean;
  label: string;
  /** Called whenever the shown status changes (e.g. to offer a fallback background). */
  onStatus?: (status: PlayerStatus) => void;
  /** Natural size of the video, once known. */
  onFrameSize?: (width: number, height: number) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canTry = enabled && webRtcSupported();
  const [status, setStatus] = useState<Status>(canTry ? 'connecting' : 'placeholder');
  const onStatusRef = useRef(onStatus);
  useEffect(() => {
    onStatusRef.current = onStatus;
  });

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
  useEffect(() => onStatusRef.current?.(shown), [shown]);

  return (
    <div className="player" data-status={shown}>
      {shown !== 'placeholder' && (
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          aria-label={label}
          onLoadedMetadata={(e) =>
            onFrameSize?.(e.currentTarget.videoWidth, e.currentTarget.videoHeight)
          }
        />
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
          <path d="M10 0H0V10" fill="none" stroke="#23262D" strokeWidth="0.4" />
        </pattern>
      </defs>
      <rect width="160" height="90" fill="#1B1D22" />
      <rect width="160" height="90" fill="url(#grid)" />
      <path d="M0 40 L160 34" stroke="#30343C" strokeWidth="0.6" />
      <rect x="14" y="52" width="38" height="16" rx="3" fill="#262A31" stroke="#3A3F49" />
      <rect x="74" y="52" width="38" height="16" rx="3" fill="#262A31" stroke="#3A3F49" />
      <rect x="128" y="18" width="24" height="38" fill="#262A31" stroke="#3A3F49" />
    </svg>
  );
}
