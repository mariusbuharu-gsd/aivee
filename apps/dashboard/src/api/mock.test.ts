import { afterEach, describe, expect, it, vi } from 'vitest';
import { describeRule } from '../rules/describe';
import { MockApi, mockRuleFromText } from './mock';

describe('mockRuleFromText', () => {
  it('turns the demo request into an unattended-table rule', () => {
    const rule = mockRuleFromText(
      'Anunță ospătarul dacă la o masă nu a venit nimeni de 2 minute',
      'cam-sala',
    );
    expect(rule.zone_tag).toBe('table');
    expect(rule.all_of).toContainEqual({ kind: 'absent', role: 'staff', min_duration_s: 120 });
    expect(describeRule(rule)).toBe(
      'La fiecare masă, când un client stă în zonă de 2 minute și nu a venit cineva de la personal de 2 minute → mesaj pe Telegram.',
    );
  });

  it('recognises a raised hand and an entrance queue', () => {
    expect(mockRuleFromText('cineva ridică mâna', 'c').all_of[0].kind).toBe('pose');
    const queue = mockRuleFromText('coadă de 4 persoane la intrare', 'c');
    expect(queue.zone_tag).toBe('entrance');
    expect(queue.all_of[0]).toMatchObject({ kind: 'count', min_count: 4 });
  });
});

describe('MockApi timeline', () => {
  afterEach(() => vi.useRealTimers());

  it('opens and later closes an alert, and offers a staff suggestion once', async () => {
    vi.useFakeTimers();
    const api = new MockApi({ latencyMs: 0 });
    const alerts = vi.fn();
    const suggestions = vi.fn();
    api.subscribeAlerts(alerts);
    api.subscribeSuggestions(suggestions);
    await vi.advanceTimersByTimeAsync(40_000);
    const states = alerts.mock.calls.map(([e]) => `${e.zone_id}:${e.state}`);
    expect(states).toEqual([
      'z-masa-2:opened',
      'z-masa-1:opened',
      'z-masa-1:closed',
      'z-masa-2:closed',
    ]);
    expect(suggestions).toHaveBeenCalledTimes(1);
    await api.confirmSuggestion('sug-track-7');
    await vi.advanceTimersByTimeAsync(45_000);
    expect(suggestions).toHaveBeenCalledTimes(1);
    api.dispose();
  });
});

describe('MockApi demo alerts', () => {
  it('includes an object_gone alert confirmed by the AI check, with before/after snapshots', async () => {
    const api = new MockApi({ latencyMs: 0, autoplay: false });
    const alerts = await api.listAlerts();
    const gone = alerts.find((a) => a.verification);
    expect(gone?.summary_ro).toBe('Masa 1: a dispărut paharul de vin');
    expect(gone?.verification).toEqual({
      status: 'confirmed',
      summary_ro: 'Masa 1: a dispărut paharul de vin',
      object_ro: 'pahar de vin',
    });
    expect(gone?.snapshot_url).toMatch(/^data:image\/svg\+xml,/);
    expect(gone?.before_snapshot_url).toMatch(/^data:image\/svg\+xml,/);
    expect(gone?.before_snapshot_url).not.toBe(gone?.snapshot_url);
    const rules = await api.listRules();
    const rule = rules.find((r) => r.id === gone?.rule_id);
    if (!rule) throw new Error('the demo alert has no rule');
    expect(rule.all_of[0].kind).toBe('object_gone');
    expect(describeRule(rule)).toMatch(/dispare un obiect/);
    api.dispose();
  });
});

describe('MockApi videos', () => {
  afterEach(() => vi.useRealTimers());

  it('ships a finished demo clip with its alerts in clip order', async () => {
    const api = new MockApi({ latencyMs: 0, autoplay: false });
    const [demo] = await api.listVideos();
    if (!demo) throw new Error('no demo upload');
    expect(demo).toMatchObject({ filename: 'sala-1.mp4', status: 'done', progress: 1 });
    expect(demo.source_camera_id).toBe('cam-sala');
    expect(demo.duration_s).toBeGreaterThan(60);
    const alerts = await api.videoEvents(demo.id);
    expect(alerts).toHaveLength(demo.events);
    expect(alerts.length).toBeGreaterThanOrEqual(4);
    const at = alerts.map((a) => a.at_s);
    expect(at).toEqual([...at].sort((x, y) => x - y));
    expect(alerts.some((a) => a.closed_reason === 'video_end')).toBe(true);
    expect(alerts.some((a) => a.arrived_at_s !== null && a.state === 'closed')).toBe(true);
  });

  it('takes a new upload from queued through running to done', async () => {
    vi.useFakeTimers();
    const api = new MockApi({ latencyMs: 0, autoplay: false });
    const file = new File(['x'], 'terasa.mp4', { type: 'video/mp4' });
    const up = await api.uploadVideo({ file, rotate: 90, copy_from_camera_id: 'cam-sala' });
    expect(up).toMatchObject({ status: 'queued', rotate: 90, filename: 'terasa.mp4' });
    expect((await api.listVideos())[0]?.id).toBe(up.id);
    await vi.advanceTimersByTimeAsync(3_000);
    const running = await api.getVideo(up.id);
    expect(running.status).toBe('running');
    expect(running.progress).toBeGreaterThan(0);
    expect(running.progress).toBeLessThan(1);
    await vi.advanceTimersByTimeAsync(10_000);
    const done = await api.getVideo(up.id);
    expect(done).toMatchObject({ status: 'done', progress: 1 });
    expect(await api.videoEvents(up.id)).toHaveLength(done.events);
  });

  it('refuses a file that is not a video', async () => {
    const api = new MockApi({ latencyMs: 0, autoplay: false });
    const file = new File(['x'], 'poza.jpg', { type: 'image/jpeg' });
    await expect(api.uploadVideo({ file })).rejects.toMatchObject({ status: 422 });
  });
});
