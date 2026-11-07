import { useEffect, useRef, useState } from 'react';
import { pickLiveSource } from './source';
import { startWhep, webRtcSupported, whepUrl } from './whep';

export type PlayerStatus = 'connecting' | 'playing' | 'placeholder';
type Status = PlayerStatus;

/** After a failed MJPEG attempt (no frames yet, or the stream broke), try again this often. */
const MJPEG_RETRY_MS = 10_000;
/** Not every browser fires `load` for a multipart stream: also look for a decoded frame. */
const MJPEG_PROBE_MS = 500;

interface MjpegState {
  url: string | null;
  loaded: boolean;
  failed: boolean;
  attempt: number;
}

const freshMjpeg = (url: string | null): MjpegState => ({
  url,
  loaded: false,
  failed: false,
  attempt: 0,
});

/**
 * Live camera video over WebRTC (MediaMTX WHEP). When WebRTC cannot play and `mjpegUrl` is
 * given, shows the API's MJPEG of the frames a connector posts over HTTPS (cloud mode); a
 * `cloudFrames` camera goes there directly. Falls back to a placeholder grid when neither plays.
 */
export function LivePlayer({
  cameraId,
  enabled = true,
  label,
  mjpegUrl = null,
  cloudFrames = false,
  onStatus,
  onFrameSize,
}: {
  cameraId: string;
  enabled?: boolean;
  label: string;
  /** `GET /api/cameras/{id}/live.mjpg`; null (mock API) keeps WebRTC or the placeholder. */
  mjpegUrl?: string | null;
  /** The camera's source is `mqtt-frames://…`: it has no WebRTC stream. */
  cloudFrames?: boolean;
  /** Called whenever the shown status changes (e.g. to offer a fallback background). */
  onStatus?: (status: PlayerStatus) => void;
  /** Natural size of the video, once known. */
  onFrameSize?: (width: number, height: number) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const webRtc = enabled && webRtcSupported();
  const [whepFailedFor, setWhepFailedFor] = useState<string | null>(null);
  const source = enabled
    ? pickLiveSource({ webRtc, whepFailed: whepFailedFor === cameraId, mjpegUrl, cloudFrames })
    : 'placeholder';
  const [status, setStatus] = useState<Status>('connecting');
  const [mjpegState, setMjpeg] = useState<MjpegState>(() => freshMjpeg(mjpegUrl));
  const mjpeg = mjpegState.url === mjpegUrl ? mjpegState : freshMjpeg(mjpegUrl);
  const onStatusRef = useRef(onStatus);
  const onFrameSizeRef = useRef(onFrameSize);
  useEffect(() => {
    onStatusRef.current = onStatus;
    onFrameSizeRef.current = onFrameSize;
  });

  useEffect(() => {
    if (source !== 'webrtc') return;
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
      .catch(() => {
        if (!alive) return;
        setStatus('placeholder');
        setWhepFailedFor(cameraId);
      });
    return () => {
      alive = false;
      ctrl.abort();
      session?.close();
    };
  }, [cameraId, source]);

  // The first decoded frame counts as playing, whether or not `load` fired.
  const probing = source === 'mjpeg' && !mjpeg.failed && !mjpeg.loaded;
  useEffect(() => {
    if (!probing) return;
    const t = setInterval(() => {
      const img = imgRef.current;
      if (!img || img.naturalWidth === 0) return;
      setMjpeg((m) => ({ ...m, url: mjpegUrl, loaded: true }));
      onFrameSizeRef.current?.(img.naturalWidth, img.naturalHeight);
    }, MJPEG_PROBE_MS);
    return () => clearInterval(t);
  }, [probing, mjpegUrl, mjpeg.attempt]);

  useEffect(() => {
    if (source !== 'mjpeg' || !mjpeg.failed) return;
    const t = setTimeout(
      () => setMjpeg((m) => ({ ...freshMjpeg(mjpegUrl), attempt: m.attempt + 1 })),
      MJPEG_RETRY_MS,
    );
    return () => clearTimeout(t);
  }, [source, mjpeg.failed, mjpegUrl]);

  const shown: Status =
    source === 'webrtc'
      ? status
      : source === 'mjpeg'
        ? mjpeg.loaded
          ? 'playing'
          : mjpeg.failed || mjpeg.attempt > 0
            ? 'placeholder'
            : 'connecting'
        : 'placeholder';
  useEffect(() => onStatusRef.current?.(shown), [shown]);

  return (
    <div className="player" data-status={shown} data-source={source}>
      {source === 'webrtc' && shown !== 'placeholder' && (
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
      {/* After the placeholder, so the first frame paints over it even before `load`. */}
      {source === 'mjpeg' && mjpegUrl && !mjpeg.failed && (
        <img
          key={`${mjpegUrl}#${mjpeg.attempt}`}
          ref={imgRef}
          src={mjpegUrl}
          alt=""
          aria-label={label}
          onLoad={(e) => {
            setMjpeg((m) => ({ ...m, url: mjpegUrl, loaded: true }));
            onFrameSize?.(e.currentTarget.naturalWidth, e.currentTarget.naturalHeight);
          }}
          onError={() => setMjpeg((m) => ({ ...m, url: mjpegUrl, loaded: false, failed: true }))}
        />
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
