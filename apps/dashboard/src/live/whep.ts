// Minimal WHEP (WebRTC-HTTP Egress Protocol) client for MediaMTX: POST an SDP offer,
// apply the SDP answer, hand the incoming stream to the caller. No trickle ICE; we wait for
// gathering to finish (bounded) so a single round trip is enough on a LAN.

export const WHEP_BASE: string = import.meta.env.VITE_WHEP_BASE || 'http://localhost:8889';

export const whepUrl = (cameraId: string, base = WHEP_BASE) =>
  `${base.replace(/\/$/, '')}/${encodeURIComponent(cameraId)}/whep`;

export interface WhepSession {
  close: () => void;
}

export function webRtcSupported(): boolean {
  return typeof window !== 'undefined' && typeof window.RTCPeerConnection === 'function';
}

function iceGatheringDone(pc: RTCPeerConnection, timeoutMs: number): Promise<void> {
  if (pc.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    const t = setTimeout(resolve, timeoutMs);
    pc.addEventListener('icegatheringstatechange', () => {
      if (pc.iceGatheringState === 'complete') {
        clearTimeout(t);
        resolve();
      }
    });
  });
}

export async function startWhep(
  url: string,
  onStream: (stream: MediaStream) => void,
  signal?: AbortSignal,
): Promise<WhepSession> {
  const pc = new RTCPeerConnection();
  let resource: string | null = null;
  const close = () => {
    pc.close();
    if (resource) fetch(resource, { method: 'DELETE' }).catch(() => undefined);
  };
  try {
    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.addTransceiver('audio', { direction: 'recvonly' });
    pc.ontrack = (e) => {
      const stream = e.streams[0];
      if (stream) onStream(stream);
    };
    await pc.setLocalDescription(await pc.createOffer());
    await iceGatheringDone(pc, 1500);
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/sdp' },
      body: pc.localDescription?.sdp ?? '',
      signal,
    });
    if (!res.ok) throw new Error(`WHEP ${res.status}`);
    const location = res.headers.get('Location');
    if (location) resource = new URL(location, url).toString();
    await pc.setRemoteDescription({ type: 'answer', sdp: await res.text() });
    return { close };
  } catch (e) {
    close();
    throw e;
  }
}
