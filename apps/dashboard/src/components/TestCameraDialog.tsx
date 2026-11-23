import { useEffect, useState } from 'react';
import type { CameraView } from '../api/client';
import { brandOf } from '../devices/rtsp';
import { useCameraTest } from '../devices/useCameraTest';
import { Dialog } from '../ui/Dialog';
import { BusyLabel, LookingEyes } from '../ui/Eyes';
import { CameraTestOutcome } from './CameraTestOutcome';
import { TapoGuide } from './TapoGuide';

/**
 * "Testează" on a saved camera: the box opens it by `camera_id` (the stored password never
 * leaves the server) and sends one face-blurred still. Runs as soon as it opens.
 */
export function TestCameraDialog({ camera, onClose }: { camera: CameraView; onClose: () => void }) {
  const test = useCameraTest();
  const run = test.run;
  const tapo = brandOf(camera.source) === 'tapo';
  const [guideOpen, setGuideOpen] = useState(false);

  useEffect(() => {
    void run({ camera_id: camera.id }, camera.id).then((problem) => {
      if (problem?.code === 'camera_auth' && tapo) setGuideOpen(true);
    });
  }, [run, camera.id, tapo]);

  async function again() {
    const problem = await run({ camera_id: camera.id }, camera.id);
    if (problem?.code === 'camera_auth' && tapo) setGuideOpen(true);
  }

  const done = test.key === camera.id && !test.busy;
  return (
    <Dialog
      title={`Testează „${camera.name}”`}
      icon="snapshot"
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose} data-autofocus>
            Închide
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void again()}
            disabled={test.busy}
          >
            <BusyLabel busy={test.busy} idle="Testează din nou">
              Se testează…
            </BusyLabel>
          </button>
        </>
      }
    >
      <div className="camera-test">
        {!done && (
          <p className="loading small" role="status">
            <LookingEyes size={24} />
            Cutia AiVee deschide camera…
          </p>
        )}
        {done && (
          <CameraTestOutcome
            frame={test.frame}
            problem={test.problem}
            tapo={tapo}
            context="saved"
          />
        )}
        {done && tapo && test.problem?.code === 'camera_auth' && (
          <TapoGuide open={guideOpen} onToggle={setGuideOpen} />
        )}
      </div>
    </Dialog>
  );
}
