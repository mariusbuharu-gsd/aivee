import { useCallback, useEffect, useRef, useState } from 'react';
import type { CameraFrame, CameraTestInput } from '../api/client';
import { useApi } from '../api/context';
import { cameraProblem, type CameraProblem } from './cameraProblems';

export interface CameraTestState {
  busy: boolean;
  frame: CameraFrame | null;
  problem: CameraProblem | null;
  /** What the last result was taken with (e.g. the source); a result for another key is stale. */
  key: string | null;
}

const IDLE: CameraTestState = { busy: false, frame: null, problem: null, key: null };

/**
 * One "Testează" at a time: the newest answer wins, the previous still is released, and
 * nothing is set after the component goes away.
 */
export function useCameraTest() {
  const api = useApi();
  const [state, setState] = useState<CameraTestState>(IDLE);
  const seq = useRef(0);

  useEffect(() => () => state.frame?.release(), [state.frame]);
  useEffect(
    () => () => {
      seq.current++;
    },
    [],
  );

  /** Resolves with the problem (null when the camera answered), or undefined if superseded. */
  const run = useCallback(
    async (input: CameraTestInput, key: string): Promise<CameraProblem | null | undefined> => {
      const mine = ++seq.current;
      setState((s) => ({ ...s, busy: true }));
      try {
        const frame = await api.testCamera(input);
        if (mine !== seq.current) {
          frame.release();
          return undefined;
        }
        setState({ busy: false, frame, problem: null, key });
        return null;
      } catch (e) {
        if (mine !== seq.current) return undefined;
        const problem = cameraProblem(e);
        setState({ busy: false, frame: null, problem, key });
        return problem;
      }
    },
    [api],
  );

  const reset = useCallback(() => {
    seq.current++;
    setState(IDLE);
  }, []);

  return { ...state, run, reset };
}
