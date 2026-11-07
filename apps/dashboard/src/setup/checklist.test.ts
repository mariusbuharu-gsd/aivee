import { afterEach, describe, expect, it } from 'vitest';
import type { Permission } from '../api/client';
import { ROLE_PERMISSIONS } from '../api/mockAccounts';
import {
  isSetupHidden,
  isTestSent,
  markTestSent,
  progressLabel,
  setSetupHidden,
  setupSteps,
  showSetup,
  type SetupInput,
  type SetupStep,
} from './checklist';

const can = (role: keyof typeof ROLE_PERMISSIONS) => (p: Permission) =>
  ROLE_PERMISSIONS[role].includes(p);

const zone = { id: 'z', name: 'Masa 1', tag: 'table', polygon: [] } as never;

const empty: SetupInput = {
  hasLocation: true,
  cameras: [],
  rules: [],
  staffProfiles: [],
  pushOn: false,
  telegram: false,
  testSent: false,
  can: can('owner'),
};

const done = (input: SetupInput) =>
  setupSteps(input)
    .filter((s) => s.done)
    .map((s) => s.id);

describe('setupSteps', () => {
  it('lists the eight steps in order; a new owner has only the location', () => {
    const steps = setupSteps(empty);
    expect(steps.map((s) => s.id)).toEqual([
      'location',
      'camera',
      'online',
      'zones',
      'rule',
      'photos',
      'alerts',
      'test',
    ]);
    expect(done(empty)).toEqual(['location']);
    expect(progressLabel(steps)).toBe('1 din 8');
    for (const s of steps) expect(s.text.length).toBeGreaterThan(10);
  });

  it('marks camera, online, zones and rule from the API data', () => {
    const offline = { ...empty, cameras: [{ id: 'cam-1', online: false, zones: [] }] };
    expect(done(offline)).toEqual(['location', 'camera']);

    const ready: SetupInput = {
      ...empty,
      cameras: [
        { id: 'cam-1', online: false, zones: [] },
        { id: 'cam 2', online: true, zones: [zone] },
      ],
      rules: [{ enabled: false }, { enabled: true }],
    };
    expect(done(ready)).toEqual(['location', 'camera', 'online', 'zones', 'rule']);
    // The zones link opens the online camera, with its id escaped.
    expect(setupSteps(ready).find((s) => s.id === 'zones')?.to).toBe('/camere/cam%202/zone');
  });

  it('a paused rule is not an active rule', () => {
    expect(done({ ...empty, rules: [{ enabled: false }] })).not.toContain('rule');
    expect(done({ ...empty, rules: [{}] })).toContain('rule');
  });

  it('needs a staff profile with at least one photo', () => {
    expect(done({ ...empty, staffProfiles: null })).not.toContain('photos');
    expect(done({ ...empty, staffProfiles: [{ examples: 0 }] })).not.toContain('photos');
    expect(done({ ...empty, staffProfiles: [{ examples: 2 }] })).toContain('photos');
  });

  it('alerts on the phone are push on this device or a Telegram chat', () => {
    expect(done({ ...empty, pushOn: true })).toContain('alerts');
    expect(done({ ...empty, telegram: true })).toContain('alerts');
    expect(done(empty)).not.toContain('alerts');
  });

  it('the test step waits for push and is done once a test was sent', () => {
    const test = (input: SetupInput) => setupSteps(input)[7] as SetupStep;
    expect(test(empty).waitingFor).toMatch(/notificările/);
    expect(test(empty).to).toBeNull();
    expect(test({ ...empty, pushOn: true }).waitingFor).toBeNull();
    // Telegram alone does not make a push test possible.
    expect(test({ ...empty, telegram: true }).waitingFor).not.toBeNull();
    expect(test({ ...empty, testSent: true })).toMatchObject({ done: true, waitingFor: null });
  });

  it('camera-dependent steps wait for a camera; links go to the right page', () => {
    const steps = setupSteps(empty);
    for (const id of ['online', 'zones', 'rule']) {
      expect(steps.find((s) => s.id === id)?.waitingFor).toBe('Adaugă întâi o cameră.');
    }
    expect(steps.find((s) => s.id === 'zones')?.to).toBe('/dispozitive');
    expect(steps.find((s) => s.id === 'photos')?.to).toBe('/dispozitive');
    expect(steps.find((s) => s.id === 'alerts')?.to).toBe('/alerte#notificari');
  });
});

describe('roles', () => {
  it('an owner can do every step', () => {
    expect(setupSteps({ ...empty, hasLocation: false }).some((s) => s.blocked)).toBe(false);
  });

  it('a step the role lacks is blocked ("cere-i proprietarului") only while not done', () => {
    const manager = { ...empty, can: can('manager') };
    expect(
      setupSteps({ ...manager, hasLocation: false }).find((s) => s.id === 'location')?.blocked,
    ).toBe(true);
    expect(setupSteps(manager).find((s) => s.id === 'location')?.blocked).toBe(false);

    const noDevices = { ...empty, can: (p: Permission) => p !== 'devices.manage' };
    const blocked = setupSteps(noDevices)
      .filter((s) => s.blocked)
      .map((s) => s.id);
    expect(blocked).toEqual(['camera', 'online', 'zones']);
  });

  it('shows the checklist to owners and managers while a step is left, never to staff', () => {
    const steps = setupSteps(empty);
    expect(showSetup('owner', steps)).toBe(true);
    expect(showSetup('manager', steps)).toBe(true);
    expect(showSetup('staff', steps)).toBe(false);
    expect(showSetup(null, steps)).toBe(false);
    const all = setupSteps({
      ...empty,
      cameras: [{ id: 'c', online: true, zones: [zone] }],
      rules: [{ enabled: true }],
      staffProfiles: [{ examples: 3 }],
      pushOn: true,
      testSent: true,
    });
    expect(progressLabel(all)).toBe('8 din 8');
    expect(showSetup('owner', all)).toBe(false);
  });
});

describe('device flags', () => {
  afterEach(() => localStorage.clear());

  it('remembers "Ascunde" and the test per user', () => {
    expect(isSetupHidden('u-1')).toBe(false);
    setSetupHidden('u-1', true);
    expect(isSetupHidden('u-1')).toBe(true);
    expect(isSetupHidden('u-2')).toBe(false);
    setSetupHidden('u-1', false);
    expect(isSetupHidden('u-1')).toBe(false);
    markTestSent('u-2');
    expect(isTestSent('u-2')).toBe(true);
    expect(isTestSent('u-1')).toBe(false);
  });

  it('survives storage that throws', () => {
    const proto = Object.getPrototypeOf(localStorage) as Storage;
    const { getItem, setItem } = proto;
    proto.getItem = () => {
      throw new Error('blocked');
    };
    proto.setItem = () => {
      throw new Error('blocked');
    };
    try {
      expect(() => setSetupHidden('u-1', true)).not.toThrow();
      expect(isSetupHidden('u-1')).toBe(false);
      expect(() => markTestSent('u-1')).not.toThrow();
    } finally {
      proto.getItem = getItem;
      proto.setItem = setItem;
    }
  });
});
