import { describe, expect, it } from 'vitest';
import {
  BRANDS,
  brandOf,
  buildRtspUrl,
  checkHost,
  maskPassword,
  parseSourceUrl,
  replaceCredentials,
} from './rtsp';

describe('buildRtspUrl', () => {
  it('uses the detection substream of each brand', () => {
    const base = { host: '192.168.1.20', user: 'admin', password: 'secret' };
    expect(buildRtspUrl({ ...base, brand: 'tapo' })).toBe(
      'rtsp://admin:secret@192.168.1.20:554/stream2',
    );
    expect(buildRtspUrl({ ...base, brand: 'hikvision' })).toBe(
      'rtsp://admin:secret@192.168.1.20:554/Streaming/Channels/102',
    );
    expect(buildRtspUrl({ ...base, brand: 'dahua' })).toBe(
      'rtsp://admin:secret@192.168.1.20:554/cam/realmonitor?channel=1&subtype=1',
    );
    expect(buildRtspUrl({ ...base, brand: 'reolink' })).toBe(
      'rtsp://admin:secret@192.168.1.20:554/h264Preview_01_sub',
    );
  });

  it('takes the path and port of another brand from the owner', () => {
    expect(
      buildRtspUrl({
        brand: 'other',
        host: '10.0.0.7',
        user: 'u',
        password: 'p',
        path: 'live/sub',
        port: '8554',
      }),
    ).toBe('rtsp://u:p@10.0.0.7:8554/live/sub');
    expect(buildRtspUrl({ brand: 'other', host: '10.0.0.7', user: '', password: '' })).toBe(
      'rtsp://10.0.0.7:554/',
    );
  });

  it('escapes characters a password may hold and keeps a port typed with the IP', () => {
    expect(
      buildRtspUrl({
        brand: 'tapo',
        host: ' 192.168.1.20:8554 ',
        user: 'ana',
        password: 'p@ss:w/rd#1',
      }),
    ).toBe('rtsp://ana:p%40ss%3Aw%2Frd%231@192.168.1.20:8554/stream2');
  });

  it('lists every brand with a label, and "alta" last', () => {
    expect(BRANDS.map((b) => b.value)).toEqual(['tapo', 'hikvision', 'dahua', 'reolink', 'other']);
    expect(BRANDS.at(-1)?.label).toBe('Altă marcă');
  });
});

describe('checkHost', () => {
  it('accepts an IPv4 address or a hostname, with an optional port', () => {
    expect(checkHost('192.168.1.20')).toBeNull();
    expect(checkHost('192.168.1.20:554')).toBeNull();
    expect(checkHost('camera-sala.local')).toBeNull();
  });
  it('explains what is wrong in Romanian', () => {
    expect(checkHost('')).toMatch(/Scrie adresa IP/);
    expect(checkHost('192.168.1.300')).toMatch(/nu e o adresă IP/);
    expect(checkHost('rtsp://192.168.1.20')).toMatch(/doar adresa IP/);
    expect(checkHost('192.168.1.20:99999')).toMatch(/Portul/);
  });
});

describe('maskPassword', () => {
  it('hides only the password', () => {
    expect(maskPassword('rtsp://admin:secret@192.168.1.20:554/stream2')).toBe(
      'rtsp://admin:••••@192.168.1.20:554/stream2',
    );
    expect(maskPassword('rtsp://192.168.1.20/stream2')).toBe('rtsp://192.168.1.20/stream2');
    expect(maskPassword('rtsp://admin@host/x')).toBe('rtsp://admin@host/x');
    expect(maskPassword('0')).toBe('0');
  });
});

describe('parseSourceUrl and replaceCredentials', () => {
  const url = 'rtsp://ana:p%40ss@192.168.1.20:554/stream2';

  it('reads host, user and password back, decoded', () => {
    expect(parseSourceUrl(url)).toEqual({
      scheme: 'rtsp',
      user: 'ana',
      password: 'p@ss',
      host: '192.168.1.20:554',
      rest: '/stream2',
    });
    expect(parseSourceUrl('0')).toBeNull();
  });

  it('keeps the password when the edit leaves it empty', () => {
    expect(replaceCredentials(url, { host: '192.168.1.21:554', user: 'ana', password: '' })).toBe(
      'rtsp://ana:p%40ss@192.168.1.21:554/stream2',
    );
    expect(
      replaceCredentials(url, { host: '192.168.1.20:554', user: 'bob', password: 'n:ew' }),
    ).toBe('rtsp://bob:n%3Aew@192.168.1.20:554/stream2');
  });

  it('recognises the brand from the path', () => {
    expect(brandOf('rtsp://a:b@h:554/stream2')).toBe('tapo');
    expect(brandOf('rtsp://a:b@h:554/Streaming/Channels/102')).toBe('hikvision');
    expect(brandOf('rtsp://a:b@h:554/whatever')).toBe('other');
  });
});
