import { useEffect, useRef } from 'react';
import type { CameraFrame } from '../api/client';
import './CameraSetup.css';
import { problemHint, type CameraProblem, type TestContext } from '../devices/cameraProblems';
import { Banner } from '../ui/Banner';

/**
 * What "Testează" came back with: the face-blurred still as AiVee sees it, or what went
 * wrong in the API's words plus one line on what to do now.
 */
export function CameraTestOutcome({
  frame,
  problem,
  tapo = false,
  context = 'new',
}: {
  frame: CameraFrame | null;
  problem: CameraProblem | null;
  /** A Tapo camera: a refused password points to the Tapo guide. */
  tapo?: boolean;
  context?: TestContext;
}) {
  // The answer lands under the fields; in a long dialog (the Tapo guide open, a phone) it
  // would sit below the fold, so bring it into view.
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  }, [frame, problem]);
  if (!frame && !problem) return null;
  return (
    <div ref={ref} className="camera-test-outcome">
      {frame ? (
        <Still frame={frame} />
      ) : (
        problem && <Problem problem={problem} tapo={tapo} context={context} />
      )}
    </div>
  );
}

function Still({ frame }: { frame: CameraFrame }) {
  return (
    <figure className="camera-test-shot">
      <img src={frame.url} alt="Imagine de test de la cameră, cu fețele estompate" />
      <figcaption className="small" role="status">
        Camera răspunde. Așa o vede AiVee.
      </figcaption>
    </figure>
  );
}

function Problem({
  problem,
  tapo,
  context,
}: {
  problem: CameraProblem;
  tapo: boolean;
  context: TestContext;
}) {
  const hint = problemHint(problem.code, { tapo, context });
  return (
    <Banner tone="error" title="Testul nu a reușit." className="camera-problem">
      {problem.message}
      {hint && <span className="camera-problem-hint">{hint}</span>}
    </Banner>
  );
}
