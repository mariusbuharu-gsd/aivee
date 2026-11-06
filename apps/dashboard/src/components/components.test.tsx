import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { AlertItem } from '../alerts/fold';
import type { Rule, StaffSuggestion } from '../contracts';
import { fakeApi, renderWithApi } from '../test/fakeApi';
import { AlertFeed } from './AlertFeed';
import { RuleComposer } from './RuleComposer';
import { StaffPhotoUpload } from './StaffPhotoUpload';
import { SuggestionCard } from './SuggestionCard';

const rule: Rule = {
  id: 'r-1',
  camera_id: 'cam-sala',
  name: 'Masă neservită',
  prompt_ro: 'Anunță ospătarul dacă la o masă nu a venit nimeni de 1 minut',
  zone_tag: 'table',
  all_of: [
    { kind: 'present', role: 'guest', min_duration_s: 60 },
    { kind: 'absent', role: 'staff', min_duration_s: 60 },
  ],
  action: { type: 'telegram' },
  enabled: true,
};

describe('RuleComposer', () => {
  it('submits the Romanian text and shows what was understood', async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    const api = fakeApi({ createRuleFromText: vi.fn(async () => rule) });
    renderWithApi(<RuleComposer cameraId="cam-sala" onCreated={onCreated} />, api);

    const submit = screen.getByRole('button', { name: 'Creează regula' });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText('Spune-i camerei ce să vadă'), rule.prompt_ro);
    await user.click(submit);

    expect(api.createRuleFromText).toHaveBeenCalledWith(rule.prompt_ro, 'cam-sala');
    const panel = await screen.findByRole('status');
    expect(within(panel).getByText('Ce am înțeles')).toBeInTheDocument();
    expect(within(panel).getByText('Masă neservită')).toBeInTheDocument();
    expect(screen.getByTestId('rule-summary')).toHaveTextContent(
      'La fiecare masă, când un client stă în zonă de 1 minut și nu a venit cineva de la personal de 1 minut → mesaj pe Telegram.',
    );
    expect(onCreated).toHaveBeenCalledWith(rule);
    expect(screen.getByLabelText('Spune-i camerei ce să vadă')).toHaveValue('');
  });

  it('shows the API error', async () => {
    const user = userEvent.setup();
    const api = fakeApi({
      createRuleFromText: vi.fn(async () => {
        throw new Error('Nu am înțeles cererea');
      }),
    });
    renderWithApi(<RuleComposer cameraId="c" />, api);
    await user.type(screen.getByLabelText('Spune-i camerei ce să vadă'), 'ceva');
    await user.click(screen.getByRole('button', { name: 'Creează regula' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Nu am înțeles cererea');
  });
});

describe('AlertFeed', () => {
  const items: AlertItem[] = [
    {
      key: 'e-2',
      rule_id: 'r',
      camera_id: 'c',
      zone_id: 'z-2',
      summary_ro: 'Masa 2: nimeni de la personal',
      opened_at: new Date(Date.now() - 30_000).toISOString(),
      closed_at: null,
      snapshot: true,
    },
    {
      key: 'e-1',
      rule_id: 'r',
      camera_id: 'c',
      zone_id: 'z-1',
      summary_ro: 'Masa 1: ospătarul a ajuns',
      opened_at: '2026-11-06T10:00:00Z',
      closed_at: '2026-11-06T10:01:30Z',
      snapshot: true,
    },
  ];
  const names: Record<string, string> = { 'z-1': 'Masa 1', 'z-2': 'Masa 2' };

  it('renders opened and closed alerts with their zone', () => {
    render(<AlertFeed items={items} zoneName={(id) => names[id] ?? id} showSnapshot />);
    const rows = screen.getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(within(rows[0] as HTMLElement).getByText('Deschisă')).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText('Masa 2')).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText('Închisă')).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText('rezolvată în 1 min 30 s')).toBeInTheDocument();
    expect(screen.getAllByRole('img', { name: 'Captură cu fețele estompate' })).toHaveLength(2);
  });

  it('shows an empty state', () => {
    render(<AlertFeed items={[]} zoneName={(id) => id} />);
    expect(screen.getByText('Nicio alertă încă.')).toBeInTheDocument();
  });
});

describe('SuggestionCard', () => {
  const suggestion: StaffSuggestion = {
    suggestion_id: 'sug-1',
    camera_id: 'cam-sala',
    track_id: 7,
    staff_score: 0.82,
    reason_ro: 'Se mișcă între mese',
  };

  it('confirms through the API and reports the decision', async () => {
    const user = userEvent.setup();
    const onResolved = vi.fn();
    const { api } = renderWithApi(
      <SuggestionCard suggestion={suggestion} onResolved={onResolved} />,
    );
    expect(screen.getByRole('heading', { name: 'Pare angajat — confirmi?' })).toBeInTheDocument();
    expect(screen.getByText(/scor 82%/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Confirmă' }));
    expect(api.confirmSuggestion).toHaveBeenCalledWith('sug-1');
    expect(api.rejectSuggestion).not.toHaveBeenCalled();
    await waitFor(() => expect(onResolved).toHaveBeenCalledWith('sug-1', 'confirmed'));
  });

  it('rejects through the API', async () => {
    const user = userEvent.setup();
    const { api } = renderWithApi(<SuggestionCard suggestion={suggestion} />);
    await user.click(screen.getByRole('button', { name: 'Respinge' }));
    expect(api.rejectSuggestion).toHaveBeenCalledWith('sug-1');
  });
});

describe('StaffPhotoUpload', () => {
  it('uploads the chosen uniform photo', async () => {
    const user = userEvent.setup();
    const { api } = renderWithApi(<StaffPhotoUpload />);
    const file = new File(['x'], 'tricou.jpg', { type: 'image/jpeg' });
    await user.upload(screen.getByLabelText('Încarcă poză uniformă'), file);
    expect(api.uploadStaffPhoto).toHaveBeenCalledWith(file);
    expect(await screen.findByText('Poza a fost adăugată ca exemplu.')).toBeInTheDocument();
  });
});
