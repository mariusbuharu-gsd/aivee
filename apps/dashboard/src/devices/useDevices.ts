import { useEffect, useState } from 'react';
import type { DeviceView } from '../api/client';
import { useApi } from '../api/context';

/** Same pace as the metrics poll: the edge refreshes `last_seen` about every 5 s. */
export const DEVICES_POLL_MS = 5_000;

/** `GET /api/devices` by device id, polled while the page is open; empty until the first answer. */
export function useDevices(): Record<string, DeviceView> {
  const api = useApi();
  const [devices, setDevices] = useState<Record<string, DeviceView>>({});
  useEffect(() => {
    let alive = true;
    const load = () =>
      api.listDevices().then(
        (list) => alive && setDevices(Object.fromEntries(list.map((d) => [d.device, d]))),
        () => undefined, // keep the last answer; the layout banner already reports outages
      );
    void load();
    const t = setInterval(load, DEVICES_POLL_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [api]);
  return devices;
}
