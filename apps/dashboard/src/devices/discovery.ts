// "Caută camere": turning what the AiVee box found on the venue network into something an
// owner can pick, and into the saved camera (source, id) without showing them either.
import type { CameraView, DeviceView, DiscoveredBrand, DiscoveredCamera } from '../api/client';
import { brandInfo, buildRtspUrl, parseSourceUrl, type CameraBrand } from './rtsp';

const LABEL: Record<DiscoveredBrand, string> = {
  tapo: 'Tapo',
  hikvision: 'Hikvision',
  dahua: 'Dahua',
  reolink: 'Reolink',
  unknown: 'Cameră IP',
};

export const discoveredBrandLabel = (b: DiscoveredBrand): string => LABEL[b] ?? LABEL.unknown;

/** The manual form's brand for a discovered one. */
export const toCameraBrand = (b: DiscoveredBrand): CameraBrand => (b === 'unknown' ? 'other' : b);

/** "Tapo C210", or just "Tapo" when the model is unknown. */
export function discoveredTitle(c: DiscoveredCamera): string {
  const model = c.model?.trim();
  return model ? `${discoveredBrandLabel(c.brand)} ${model}` : discoveredBrandLabel(c.brand);
}

/** The user name most cameras of that brand ship with; Tapo has none (the owner creates it). */
export const defaultUser = (b: DiscoveredBrand): string => brandInfo(toCameraBrand(b)).user;

/**
 * The address the box opens: the first path the scan found, else the brand's substream.
 * The password stays inside it; the owner path never displays it.
 */
export function discoveredSource(c: DiscoveredCamera, user: string, password: string): string {
  const brand = toCameraBrand(c.brand);
  const path = c.rtsp_paths[0] ?? brandInfo(brand).path;
  return buildRtspUrl({
    brand: 'other',
    host: c.ip,
    port: String(c.port || 554),
    path: path || '/',
    user,
    password,
  });
}

/** Same IP as a camera the location already has (what `already_added` says, checked locally). */
export function usesIp(camera: Pick<CameraView, 'source'>, ip: string): boolean {
  const host = parseSourceUrl(camera.source)?.host ?? '';
  return host.replace(/:\d+$/, '') === ip;
}

const MAX_ID = 64;

/**
 * A camera id from its name, never shown: "Sala mare" → "cam-sala-mare", "cam-sala-mare-2"
 * when taken. Letters, digits and "-" only, as the API and the edge expect.
 */
export function cameraIdFor(name: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  const slug = name
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40)
    .replace(/-+$/, '');
  const base = `cam-${slug || 'ip'}`;
  if (!used.has(base)) return base;
  for (let n = 2; ; n++) {
    const id = `${base}-${n}`.slice(0, MAX_ID);
    if (!used.has(id)) return id;
  }
}

/** An online AiVee box with the words the owner sees for it (never its id). */
export interface BoxChoice {
  device: string;
  label: string;
  /** The cameras it already serves, by name. */
  detail: string;
}

/**
 * Online boxes to pick from, labelled "Cutia AiVee 1", "Cutia AiVee 2", … with the cameras
 * each already serves, so two boxes can be told apart without their ids.
 */
export function onlineBoxes(devices: DeviceView[], cameras: CameraView[]): BoxChoice[] {
  const online = devices.filter((d) => d.state === 'online');
  return online.map((d, i) => {
    const names = cameras.filter((c) => c.device === d.device).map((c) => c.name);
    return {
      device: d.device,
      label: online.length === 1 ? 'Cutia AiVee' : `Cutia AiVee ${i + 1}`,
      detail: names.length ? `Vede deja: ${names.join(', ')}` : 'Încă fără camere',
    };
  });
}
