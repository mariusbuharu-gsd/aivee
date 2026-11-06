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
