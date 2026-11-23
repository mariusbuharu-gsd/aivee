import { describe, expect, it } from 'vitest';
import { ApiError, type DiscoveredCamera } from '../api/client';
import { asCameraProblem, cameraProblem, problemHint } from './cameraProblems';
import {
  cameraIdFor,
  defaultUser,
  discoveredSource,
  discoveredTitle,
  onlineBoxes,
  usesIp,
} from './discovery';

const tapo: DiscoveredCamera = {
  ip: '192.168.1.23',
  port: 554,
  brand: 'tapo',
  model: 'C210',
  name: null,
  onvif: true,
  rtsp_paths: ['/stream2', '/stream1'],
  already_added: false,
};

describe('discovered cameras', () => {
  it('builds the source from IP, port, the first path and the account', () => {
    expect(discoveredSource(tapo, 'ana', 'p@ss')).toBe(
      'rtsp://ana:p%40ss@192.168.1.23:554/stream2',
    );
    expect(discoveredSource({ ...tapo, port: 8554 }, 'a', 'b')).toBe(
      'rtsp://a:b@192.168.1.23:8554/stream2',
    );
  });

  it("falls back to the brand's substream when the scan found no path", () => {
    const hik = { ...tapo, brand: 'hikvision' as const, rtsp_paths: [] };
    expect(discoveredSource(hik, 'admin', 'x')).toBe(
      'rtsp://admin:x@192.168.1.23:554/Streaming/Channels/102',
    );
  });

  it('names a camera by brand and model, and prefills the usual user', () => {
    expect(discoveredTitle(tapo)).toBe('Tapo C210');
    expect(discoveredTitle({ ...tapo, brand: 'unknown', model: null })).toBe('Cameră IP');
    expect(defaultUser('tapo')).toBe('');
    expect(defaultUser('hikvision')).toBe('admin');
    expect(defaultUser('unknown')).toBe('admin');
  });

  it('tells whether a saved camera already uses an IP', () => {
    expect(usesIp({ source: 'rtsp://u:p@192.168.1.23:554/stream2' }, '192.168.1.23')).toBe(true);
    expect(usesIp({ source: 'rtsp://192.168.1.230/stream2' }, '192.168.1.23')).toBe(false);
    expect(usesIp({ source: 'mqtt-frames://cam-1' }, '192.168.1.23')).toBe(false);
  });
});

describe('cameraIdFor', () => {
  it('slugs the name without diacritics and keeps it unique', () => {
    expect(cameraIdFor('Sala mare', [])).toBe('cam-sala-mare');
    expect(cameraIdFor('Terasă', [])).toBe('cam-terasa');
    expect(cameraIdFor('Bar', ['cam-bar', 'cam-bar-2'])).toBe('cam-bar-3');
    expect(cameraIdFor('  ✨ ', [])).toBe('cam-ip');
    expect(cameraIdFor('x'.repeat(100), [])).toMatch(/^cam-x{40}$/);
  });
});

describe('onlineBoxes', () => {
  const cameras = [
    { id: 'c1', name: 'Sala', device: 'edge-a', source: '', online: true, zones: [] },
    { id: 'c2', name: 'Bar', device: 'edge-a', source: '', online: true, zones: [] },
  ];

  it('lists only online boxes, by number and the cameras they serve, never by id', () => {
    const boxes = onlineBoxes(
      [
        { device: 'edge-a', state: 'online' },
        { device: 'edge-b', state: 'offline' },
        { device: 'edge-c', state: 'online' },
      ],
      cameras,
    );
    expect(boxes).toEqual([
      { device: 'edge-a', label: 'Cutia AiVee 1', detail: 'Vede deja: Sala, Bar' },
      { device: 'edge-c', label: 'Cutia AiVee 2', detail: 'Încă fără camere' },
    ]);
  });

  it('calls a single box just "Cutia AiVee"', () => {
    expect(onlineBoxes([{ device: 'edge-a', state: 'online' }], [])[0]?.label).toBe('Cutia AiVee');
  });
});

describe('camera problems', () => {
  it("keeps the API's Romanian message", () => {
    const e = new ApiError('Parolă greșită pentru camera de la 192.168.1.23.', 'camera_auth', 422);
    expect(cameraProblem(e)).toEqual({ code: 'camera_auth', message: e.message });
  });

  it('names a bare 409 or 504 from a gateway as the box being offline or slow', () => {
    expect(asCameraProblem(new ApiError('Există deja.', 'error', 409))).toMatchObject({
      code: 'device_offline',
      message: 'Cutia AiVee nu e conectată acum.',
    });
    expect(cameraProblem(new ApiError('Eroare de server (504).', 'error', 504))).toEqual({
      code: 'device_timeout',
      message: 'Cutia AiVee nu a răspuns la timp.',
    });
  });

  it('fills in a known code that came without a message', () => {
    expect(cameraProblem(new ApiError('', 'camera_no_stream', 422)).message).toBe(
      'Camera răspunde, dar nu trimite imagine.',
    );
  });

  it('leaves other errors alone', () => {
    expect(cameraProblem(new ApiError('Serverul nu răspunde.', 'network'))).toEqual({
      code: 'other',
      message: 'Serverul nu răspunde.',
    });
    expect(cameraProblem(new Error('boom')).code).toBe('other');
  });

  it('points Tapo owners to the camera account, others to the admin account', () => {
    expect(problemHint('camera_auth', { tapo: true })).toMatch(/nu contul tău Tapo/);
    expect(problemHint('camera_auth')).toMatch(/utilizatorul și parola de admin/);
    expect(problemHint('camera_auth', { context: 'saved' })).toMatch(/Editează camera/);
    expect(problemHint('other')).toBeNull();
  });
});
