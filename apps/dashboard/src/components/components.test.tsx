import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { AlertItem } from '../alerts/fold';
import type { Rule, StaffSuggestion } from '../contracts';
import { fakeApi, renderWithApi } from '../test/fakeApi';
import { ApiError } from '../api/client';
import { AddCameraForm } from './AddCameraForm';
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
  const draft = { rule, explanation_ro: 'Vă anunț când la o masă nu vine nimeni de 1 minut.' };
  const typeRequest = async (user: ReturnType<typeof userEvent.setup>, text = rule.prompt_ro) => {
    await user.type(screen.getByLabelText('Spune-i camerei ce să vadă'), text);
    await user.click(screen.getByRole('button', { name: 'Creează regula' }));
  };

  it('shows the draft first and saves it only on confirm', async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    const api = fakeApi({ draftRuleFromText: vi.fn(async () => draft) });
    renderWithApi(<RuleComposer cameraId="cam-sala" onCreated={onCreated} />, api);

    expect(screen.getByRole('button', { name: 'Creează regula' })).toBeDisabled();
    await typeRequest(user);

    expect(api.draftRuleFromText).toHaveBeenCalledWith(rule.prompt_ro, 'cam-sala');
    const panel = await screen.findByRole('region', { name: 'Ce am înțeles' });
    expect(within(panel).getByText('Masă neservită')).toBeInTheDocument();
    expect(within(panel).getByText('ciornă')).toBeInTheDocument();
    expect(screen.getByTestId('rule-explanation')).toHaveTextContent(draft.explanation_ro);
    expect(screen.getByTestId('rule-summary')).toHaveTextContent(
      'La fiecare masă, când un client stă în zonă de 1 minut și nu a venit cineva de la personal de 1 minut → mesaj pe Telegram.',
    );
    expect(api.createRule).not.toHaveBeenCalled();
    expect(onCreated).not.toHaveBeenCalled();

    await user.click(within(panel).getByRole('button', { name: /Confirmă și salvează/ }));
    expect(api.createRule).toHaveBeenCalledWith(rule);
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Regula „Masă neservită” a fost salvată',
    );
    expect(onCreated).toHaveBeenCalledWith(rule);
    expect(screen.queryByRole('region', { name: 'Ce am înțeles' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Spune-i camerei ce să vadă')).toHaveValue('');
  });

  it('lets the user edit the draft before saving', async () => {
    const user = userEvent.setup();
    const api = fakeApi({ draftRuleFromText: vi.fn(async () => draft) });
    renderWithApi(<RuleComposer cameraId="cam-sala" />, api);
    await typeRequest(user);
    await user.click(await screen.findByRole('button', { name: /Modifică/ }));
    const name = screen.getByLabelText('Nume');
    await user.clear(name);
    await user.type(name, 'Masă uitată');
    const first = screen.getByLabelText('Durată condiția 1 (secunde)');
    await user.clear(first);
    await user.type(first, '120');
    await user.click(screen.getByRole('button', { name: /Confirmă și salvează/ }));
    expect(api.createRule).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Masă uitată',
        all_of: [
          { kind: 'present', role: 'guest', min_duration_s: 120 },
          { kind: 'absent', role: 'staff', min_duration_s: 60 },
        ],
      }),
    );
  });

  it('discards the draft without saving', async () => {
    const user = userEvent.setup();
    const api = fakeApi({ draftRuleFromText: vi.fn(async () => draft) });
    renderWithApi(<RuleComposer cameraId="cam-sala" />, api);
    await typeRequest(user);
    await user.click(await screen.findByRole('button', { name: 'Renunță' }));
    expect(screen.queryByRole('region', { name: 'Ce am înțeles' })).not.toBeInTheDocument();
    expect(api.createRule).not.toHaveBeenCalled();
  });

  it('shows the Romanian API error', async () => {
    const user = userEvent.setup();
    const api = fakeApi({
      draftRuleFromText: vi.fn(async () => {
        throw new ApiError('Camera nu are nicio zonă de tip „table”.', 'clarify', 422);
      }),
    });
    renderWithApi(<RuleComposer cameraId="c" />, api);
    await typeRequest(user, 'ceva');
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Camera nu are nicio zonă de tip „table”.',
    );
  });
});

describe('AddCameraForm', () => {
  it('creates the camera with the edge defaults prefilled', async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    const { api } = renderWithApi(<AddCameraForm onCreated={onCreated} />);
    expect(screen.getByLabelText('Id cameră')).toHaveValue('cam-01');
    expect(screen.getByLabelText('Dispozitiv')).toHaveValue('edge-01');
    await user.type(screen.getByLabelText('Nume'), 'Sala');
    await user.type(screen.getByLabelText(/Adresa sursei/), 'rtsp://cam/1');
    await user.click(screen.getByRole('button', { name: 'Adaugă camera' }));
    const sent = { id: 'cam-01', name: 'Sala', source: 'rtsp://cam/1', device: 'edge-01' };
    expect(api.createCamera).toHaveBeenCalledWith(sent);
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(expect.objectContaining(sent)));
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
      snapshot_url: 'http://api/api/snapshots/e-2',
    },
    {
      key: 'e-1',
      rule_id: 'r',
      camera_id: 'c',
      zone_id: 'z-1',
      summary_ro: 'Masa 1: ospătarul a ajuns',
      opened_at: '2026-11-06T10:00:00Z',
      closed_at: '2026-11-06T10:01:30Z',
      snapshot: false,
      snapshot_url: null,
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
    // Only the alert with a snapshot gets one; no grey placeholder for the other.
    const shots = screen.getAllByRole('img', { name: 'Captură cu fețele estompate' });
    expect(shots).toHaveLength(1);
    expect(shots[0]).toHaveAttribute('src', 'http://api/api/snapshots/e-2');
    fireEvent.error(shots[0] as HTMLElement);
    expect(screen.queryByRole('img', { name: 'Captură cu fețele estompate' })).toBeNull();
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
