// "Configurare": the steps from a new account to the first real alert, computed only from data
// the API already serves (cameras, rules, staff profiles, the location) plus two facts that live
// on this device (push subscription, a successful test push). Pure, so it is tested without React.
import type { CameraView, Permission, Role, StaffProfile } from '../api/client';
import type { Rule } from '../contracts';

export type SetupStepId =
  'location' | 'camera' | 'online' | 'zones' | 'rule' | 'photos' | 'alerts' | 'test';

export interface SetupInput {
  /** The current location exists (the signed-in user has one selected). */
  hasLocation: boolean;
  /** Cameras at the current location. */
  cameras: Pick<CameraView, 'id' | 'online' | 'zones'>[];
  rules: Pick<Rule, 'enabled'>[];
  /** Null when unknown (no `staff.enrol`, or the request failed): the step counts as to do. */
  staffProfiles: Pick<StaffProfile, 'examples'>[] | null;
  /** This device is subscribed to push notifications. */
  pushOn: boolean;
  /** The current location has a Telegram chat. */
  telegram: boolean;
  /** A test push reached at least one device (remembered on this device). */
  testSent: boolean;
  can: (permission: Permission) => boolean;
}

export interface SetupStep {
  id: SetupStepId;
  title: string;
  /** One line: what the step is and why it matters. */
  text: string;
  done: boolean;
  /** Not done and the user's role cannot do it: "cere-i proprietarului". */
  blocked: boolean;
  /** Deep link for the step's button; null for the inline "Trimite un test". */
  to: string | null;
  action: string;
  /** Set when a previous step must be done first; the button is disabled with this hint. */
  waitingFor: string | null;
}

export const SETUP_TOTAL = 8;

/** The checklist, in order. */
export function setupSteps(input: SetupInput): SetupStep[] {
  const { cameras, can } = input;
  const camera = cameras.find((c) => c.online) ?? cameras[0];
  const hasCamera = cameras.length > 0;
  const step = (
    id: SetupStepId,
    title: string,
    text: string,
    done: boolean,
    permission: Permission,
    to: string | null,
    action: string,
    waitingFor: string | null = null,
  ): SetupStep => ({
    id,
    title,
    text,
    done,
    blocked: !done && !can(permission),
    to,
    action,
    waitingFor: done ? null : waitingFor,
  });
  return [
    step(
      'location',
      'Locație creată',
      'Restaurantul, terasa sau magazinul unde montezi camerele.',
      input.hasLocation,
      'locations.manage',
      '/locatii',
      'Adaugă locația',
    ),
    step(
      'camera',
      'Cameră adăugată',
      'Leagă o cameră din sală de această locație.',
      hasCamera,
      'devices.manage',
      '/dispozitive',
      'Adaugă cameră',
    ),
    step(
      'online',
      'Cameră online',
      'Dispozitivul de lângă cameră trebuie să fie pornit și conectat la internet.',
      cameras.some((c) => c.online),
      'devices.manage',
      '/dispozitive',
      'Vezi dispozitivele',
      hasCamera ? null : 'Adaugă întâi o cameră.',
    ),
    step(
      'zones',
      'Zone desenate',
      'Desenează pe imagine mesele și intrarea pe care le urmărește camera.',
      cameras.some((c) => (c.zones?.length ?? 0) > 0),
      'devices.manage',
      camera ? `/camere/${encodeURIComponent(camera.id)}/zone` : '/dispozitive',
      'Desenează zonele',
      hasCamera ? null : 'Adaugă întâi o cameră.',
    ),
    step(
      'rule',
      'Regulă activă',
      'Scrie în română ce să urmărească, de exemplu o masă la care nu vine nimeni.',
      input.rules.some((r) => r.enabled !== false),
      'rules.manage',
      '/reguli',
      'Scrie o regulă',
      hasCamera ? null : 'Adaugă întâi o cameră.',
    ),
    step(
      'photos',
      'Poze cu uniforma',
      'Pe Camere, „Adaugă angajat” filmează un coleg 20 s, ca AiVee să deosebească personalul de clienți.',
      (input.staffProfiles ?? []).some((p) => p.examples > 0),
      'staff.enrol',
      // The 20 s capture on the camera card replaced uploading photos as the main way.
      '/dispozitive',
      'Adaugă angajat',
    ),
    step(
      'alerts',
      'Alerte pe telefon',
      'Pornește notificările pe acest telefon sau leagă un chat Telegram de locație.',
      input.pushOn || input.telegram,
      'alerts.view',
      '/alerte#notificari',
      'Activează notificările',
    ),
    step(
      'test',
      'Alertă de test trimisă',
      'Trimite-ți o notificare de probă, ca să vezi cum arată o alertă.',
      input.testSent,
      'alerts.view',
      null,
      'Trimite un test',
      input.pushOn ? null : 'Pornește întâi notificările pe acest telefon.',
    ),
  ];
}

export function setupProgress(steps: SetupStep[]): { done: number; total: number } {
  return { done: steps.filter((s) => s.done).length, total: steps.length };
}

/** "3 din 8". */
export function progressLabel(steps: SetupStep[]): string {
  const { done, total } = setupProgress(steps);
  return `${done} din ${total}`;
}

/** "Mai ai 2 pași: Poze cu uniforma, Alerte pe telefon": the collapsed one-liner. */
export function remainingLabel(steps: SetupStep[]): string {
  const left = steps.filter((s) => !s.done);
  const n = left.length === 1 ? '1 pas' : `${left.length} pași`;
  return `Mai ai ${n}: ${left.map((s) => s.title).join(', ')}`;
}

/** With this many steps left or fewer, the card starts as one line. */
export const FEW_LEFT = 2;

/** Owners and managers see the checklist until every step is done; staff never do. */
export function showSetup(role: Role | null | undefined, steps: SetupStep[]): boolean {
  if (role !== 'owner' && role !== 'manager') return false;
  return steps.some((s) => !s.done);
}

// --- per-user flags on this device (localStorage may throw: private mode, blocked storage) ----

const HIDDEN_KEY = 'aivee.setup.hidden';
const TESTED_KEY = 'aivee.setup.tested';

function readFlag(key: string, userId: string): boolean {
  try {
    return localStorage.getItem(`${key}.${userId}`) === '1';
  } catch {
    return false;
  }
}

function writeFlag(key: string, userId: string, on: boolean): void {
  try {
    if (on) localStorage.setItem(`${key}.${userId}`, '1');
    else localStorage.removeItem(`${key}.${userId}`);
  } catch {
    /* not remembered; the card shows again next time */
  }
}

export const isSetupHidden = (userId: string) => readFlag(HIDDEN_KEY, userId);
export const setSetupHidden = (userId: string, hidden: boolean) =>
  writeFlag(HIDDEN_KEY, userId, hidden);
export const isTestSent = (userId: string) => readFlag(TESTED_KEY, userId);
export const markTestSent = (userId: string) => writeFlag(TESTED_KEY, userId, true);
