import type { CameraView } from '../api/client';

/**
 * The camera a page opens on: the first online one that is already set up (has zones or rules),
 * else the first online one, else simply the first. Picking an offline camera by default made
 * the demo start on a dead tile.
 */
export function defaultCamera(
  cameras: CameraView[],
  rules: { camera_id: string }[] = [],
): CameraView | undefined {
  const setUp = (c: CameraView) =>
    (c.zones?.length ?? 0) > 0 || rules.some((r) => r.camera_id === c.id);
  return cameras.find((c) => c.online && setUp(c)) ?? cameras.find((c) => c.online) ?? cameras[0];
}
