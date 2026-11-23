// What can go wrong when the AiVee box tests or looks for a camera, in words an owner can act
// on. The API's `message_ro` is shown first; these are the fallbacks when it sends none, plus a
// "what to do now" line per problem.
import { ApiError } from '../api/client';

export type CameraProblemCode =
  | 'camera_auth'
  | 'camera_unreachable'
  | 'camera_no_stream'
  | 'device_required'
  | 'device_offline'
  | 'device_timeout';

/** Shown when the API answers with a known code but no `message_ro` (a proxy, an older API). */
export const CAMERA_PROBLEM_RO: Record<CameraProblemCode, string> = {
  camera_auth: 'Camera a refuzat utilizatorul sau parola.',
  camera_unreachable: 'Cutia AiVee nu ajunge la cameră.',
  camera_no_stream: 'Camera răspunde, dar nu trimite imagine.',
  device_required: 'Alege cutia AiVee care să testeze camera.',
  device_offline: 'Cutia AiVee nu e conectată acum.',
  device_timeout: 'Cutia AiVee nu a răspuns la timp.',
};

const CODES = new Set<string>(Object.keys(CAMERA_PROBLEM_RO));

export const isCameraProblem = (code: string): code is CameraProblemCode => CODES.has(code);

/**
 * The same error with a camera code: a 409 or 504 without one (a gateway's own page) becomes
 * `device_offline` / `device_timeout`, and a known code without a Romanian message gets ours.
 */
export function asCameraProblem(err: ApiError): ApiError {
  let code = err.code;
  if (!isCameraProblem(code)) {
    if (err.status === 409) code = 'device_offline';
    else if (err.status === 504) code = 'device_timeout';
    else return err;
  }
  const generic = !isCameraProblem(err.code) || !err.message.trim();
  return new ApiError(
    generic ? CAMERA_PROBLEM_RO[code as CameraProblemCode] : err.message,
    code,
    err.status,
  );
}

export interface CameraProblem {
  code: CameraProblemCode | 'other';
  /** The API's sentence, or ours. */
  message: string;
}

export function cameraProblem(err: unknown): CameraProblem {
  if (err instanceof ApiError) {
    const e = asCameraProblem(err);
    return { code: isCameraProblem(e.code) ? e.code : 'other', message: e.message };
  }
  return { code: 'other', message: 'Nu am putut vorbi cu camera. Încearcă din nou.' };
}

/** Where the test runs: before saving (wizard, manual form) or on a saved camera's card. */
export type TestContext = 'new' | 'saved';

/** One line on what to do now; `null` when the message already says it all. */
export function problemHint(
  code: CameraProblem['code'],
  { tapo = false, context = 'new' }: { tapo?: boolean; context?: TestContext } = {},
): string | null {
  switch (code) {
    case 'camera_auth':
      if (tapo) {
        return context === 'saved'
          ? 'Tapo cere contul camerei, nu contul tău Tapo. Fă-l după cei 3 pași pentru Tapo, apoi schimbă parola la „Editează camera”.'
          : 'Tapo cere contul camerei, nu contul tău Tapo. Fă-l după cei 3 pași pentru Tapo.';
      }
      return context === 'saved'
        ? 'Folosește utilizatorul și parola de admin ale camerei; schimbă-le la „Editează camera”.'
        : 'Folosește utilizatorul și parola de admin ale camerei. Atenție la literele mari.';
    case 'camera_unreachable':
      return context === 'saved'
        ? 'Camera e pornită și în același router cu cutia AiVee? Dacă routerul a repornit, adresa ei s-a putut schimba: scoate camera și adaug-o din nou cu „Caută camere”.'
        : 'Camera e pornită și în același router cu cutia AiVee? Dacă routerul a repornit, caută din nou camerele: adresa ei s-a putut schimba.';
    case 'camera_no_stream':
      return tapo
        ? 'Pornește Third-Party Compatibility în aplicația Tapo (pasul 2 pentru Tapo), apoi testează din nou.'
        : 'Așteaptă un minut și testează din nou. Dacă tot nu merge, adaug-o manual și alege marca.';
    case 'device_required':
      return 'Alege mai sus cutia AiVee din aceeași rețea cu camera.';
    case 'device_offline':
      return 'Verifică să aibă lumina aprinsă și cablul de rețea în priză, apoi încearcă din nou.';
    case 'device_timeout':
      return 'Încearcă din nou. Dacă se repetă, scoate cutia din priză 10 secunde și repornește-o.';
    default:
      return null;
  }
}
