// What went wrong on the phone page, in words a presenter can act on (Romanian UI copy).
import type { ApiError } from '../api/client';

export interface Problem {
  title: string;
  text?: string;
  login?: boolean;
}

/** Why the camera did not start, in words a presenter can act on. */
export function cameraProblem(e: unknown): Problem {
  const name = e instanceof DOMException ? e.name : '';
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return {
      title: 'Ai refuzat accesul la cameră',
      text: 'Permite camera din setările browserului (iconița de lângă adresă), apoi apasă din nou „Pornește camera”.',
    };
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return { title: 'Nu găsesc o cameră pe acest telefon' };
  }
  if (name === 'NotReadableError') {
    return {
      title: 'Camera e folosită de altă aplicație',
      text: 'Închide aplicația care filmează, apoi încearcă din nou.',
    };
  }
  return { title: 'Camera nu a pornit', text: e instanceof Error ? e.message : undefined };
}

/** A refused frame the sender gave up on. */
export function sendProblem(e: ApiError): Problem {
  if (e.status === 401) {
    return { title: 'Nu mai ești autentificat', text: 'Intră din nou în cont.', login: true };
  }
  if (e.status === 403) {
    return {
      title: 'Contul tău nu poate trimite imagini',
      text: 'Doar proprietarul sau managerul locației poate folosi telefonul ca cameră.',
    };
  }
  return { title: 'Serverul a refuzat imaginile', text: e.message };
}
