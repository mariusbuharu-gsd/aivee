import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { AlertItem } from '../alerts/fold';
import type { Rule, StaffSuggestion } from '../contracts';
import { fakeApi, renderWithApi } from '../test/fakeApi';
import { ApiError } from '../api/client';
import { AddCameraForm } from './AddCameraForm';
import { ruleLimitS } from '../alerts/limit';
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

  it('says next to the field what is wrong, before calling the API', async () => {
    const user = userEvent.setup();
    const { api } = renderWithApi(<AddCameraForm />);
    await user.clear(screen.getByLabelText('Id cameră'));
    await user.type(screen.getByLabelText('Id cameră'), 'cam 01');
    await user.click(screen.getByRole('button', { name: 'Adaugă camera' }));
    expect(api.createCamera).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Nume')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('Id cameră')).toHaveAccessibleDescription(/Fără spații/);
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
    expect(within(rows[1] as HTMLElement).getByText('a durat 1 min 30 s')).toBeInTheDocument();
    // Only the alert with a snapshot gets one; no grey placeholder for the other.
    const shots = screen.getAllByRole('img', { name: 'Captură cu fețele estompate' });
    expect(shots).toHaveLength(1);
    expect(shots[0]).toHaveAttribute('src', 'http://api/api/snapshots/e-2');
    fireEvent.error(shots[0] as HTMLElement);
    expect(screen.queryByRole('img', { name: 'Captură cu fețele estompate' })).toBeNull();
  });

  const gone: AlertItem = {
    key: 'e-9',
    rule_id: 'r-pahar',
    camera_id: 'c',
    zone_id: 'z-1',
    summary_ro: 'Masa 1: a dispărut un obiect',
    opened_at: new Date(Date.now() - 30_000).toISOString(),
    closed_at: null,
    snapshot: true,
    snapshot_url: 'http://api/api/snapshots/e-9',
    before_snapshot_url: 'http://api/api/snapshots/e-9-before',
    verification: {
      status: 'confirmed',
      summary_ro: 'Masa 1: a dispărut paharul de vin',
      object_ro: 'pahar de vin',
    },
  };

  it('shows the AI verdict, its summary and the before/after snapshots', () => {
    render(<AlertFeed items={[gone]} zoneName={(id) => names[id] ?? id} showSnapshot />);
    expect(screen.getByText('Confirmat de AI')).toBeInTheDocument();
    expect(screen.getByText('Masa 1: a dispărut paharul de vin')).toBeInTheDocument();
    expect(screen.getByText('Înainte')).toBeInTheDocument();
    expect(screen.getByText('După')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /^Înainte/ })).toHaveAttribute(
      'src',
      'http://api/api/snapshots/e-9-before',
    );
    expect(screen.getByRole('img', { name: /^După/ })).toHaveAttribute(
      'src',
      'http://api/api/snapshots/e-9',
    );
  });

  it.each([
    ['rejected', 'Neconfirmat'],
    ['pending', 'Se verifică…'],
  ] as const)('labels a %s verification', (status, label) => {
    render(
      <AlertFeed
        items={[{ ...gone, verification: { status } }]}
        zoneName={(id) => names[id] ?? id}
      />,
    );
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it('looks like a plain alert when the AI check is unavailable', () => {
    render(
      <AlertFeed
        items={[{ ...gone, verification: { status: 'unavailable', summary_ro: 'ignorat' } }]}
        zoneName={(id) => names[id] ?? id}
        showSnapshot
      />,
    );
    expect(screen.queryByText(/Confirmat de AI|Neconfirmat|Se verifică/)).toBeNull();
    expect(screen.queryByText('ignorat')).toBeNull();
    expect(screen.queryByText('Înainte')).toBeNull();
    const shots = screen.getAllByRole('img');
    expect(shots).toHaveLength(1);
    expect(shots[0]).toHaveAccessibleName('Captură cu fețele estompate');
    expect(shots[0]).toHaveAttribute('src', 'http://api/api/snapshots/e-9');
  });

  it('shows an empty state', () => {
    render(<AlertFeed items={[]} zoneName={(id) => id} />);
    expect(screen.getByText('Nicio alertă încă.')).toBeInTheDocument();
  });

  it('hero: an open alert large, with snapshot, running clock, rule and optional "Merg eu"', async () => {
    const onAck = vi.fn(async () => undefined);
    renderWithApi(
      <AlertFeed
        variant="hero"
        items={[items[0] as AlertItem]}
        zoneName={(id) => names[id] ?? id}
        showSnapshot
        ruleName={(id) => (id === 'r' ? 'Masă neservită' : undefined)}
        onAck={onAck}
      />,
    );
    const card = screen.getByRole('list', { name: 'Alerte deschise' });
    expect(
      within(card).getByRole('heading', { name: 'Masa 2: nimeni de la personal' }),
    ).toBeVisible();
    expect(within(card).getByText(/regula „Masă neservită”/)).toBeInTheDocument();
    expect(within(card).getByText(/^00:\d\d$/)).toBeInTheDocument();
    expect(within(card).getByRole('img', { name: 'Captură cu fețele estompate' })).toHaveAttribute(
      'src',
      'http://api/api/snapshots/e-2',
    );
    expect(within(card).getByText(/Opțional: colegii văd că vii/)).toBeInTheDocument();
    await userEvent.click(within(card).getByRole('button', { name: 'Merg eu la Masa 2' }));
    expect(onAck).toHaveBeenCalledWith('e-2');
  });

  it('rows: one line per closed alert with a bar against the rule threshold', () => {
    const closed = items[1] as AlertItem; // open 90 s
    const { container } = render(
      <AlertFeed
        variant="rows"
        items={[closed, { ...closed, key: 'e-3', closed_at: '2026-11-06T10:00:30Z' }]}
        zoneName={(id) => names[id] ?? id}
        limit={(a) => (a.key === 'e-1' ? { seconds: 60, ofRule: true } : null)}
      />,
    );
    const rows = within(screen.getByRole('list', { name: 'Alerte închise' })).getAllByRole(
      'listitem',
    );
    expect(rows).toHaveLength(2);
    expect(within(rows[0] as HTMLElement).getByText('Masa 1')).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText('ospătarul a ajuns')).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText('01:30 ·')).toBeInTheDocument();
    const bars = container.querySelectorAll('.dur-bar');
    // Past the 60 s limit: full and coral. No scale for the second row: no bar.
    expect(bars).toHaveLength(1);
    expect(bars[0]).toHaveClass('is-over');
    expect(bars[0]).toHaveAttribute('title', '1 min 30 s din limita regulii de 1 min 0 s');
    expect((bars[0]?.firstChild as HTMLElement).style.width).toBe('100%');
  });

  it('rows: a fallback scale never reads as over the limit', () => {
    const closed = items[1] as AlertItem;
    const { container } = render(
      <AlertFeed
        variant="rows"
        items={[closed]}
        zoneName={(id) => names[id] ?? id}
        limit={() => ({ seconds: 180, ofRule: false })}
      />,
    );
    const bar = container.querySelector('.dur-bar');
    expect(bar).not.toHaveClass('is-over');
    expect((bar?.firstChild as HTMLElement).style.width).toBe('50%');
  });
});

describe('ruleLimitS', () => {
  it('takes the longest condition duration, null for instant rules', () => {
    expect(ruleLimitS(rule)).toBe(60);
    expect(ruleLimitS({ all_of: [{ min_duration_s: 30 }, { min_duration_s: 180 }] })).toBe(180);
    expect(ruleLimitS({ all_of: [{}] })).toBeNull();
    expect(ruleLimitS({ all_of: [{ kind: 'object_gone', min_duration_s: 60 }] })).toBeNull();
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

  it('asks a Da/Nu question with the blurred person and the reason', async () => {
    const user = userEvent.setup();
    const onResolved = vi.fn();
    const { api } = renderWithApi(
      <SuggestionCard
        variant="question"
        suggestion={suggestion}
        cameraName="Sala"
        onResolved={onResolved}
      />,
    );
    expect(
      screen.getByRole('heading', { name: '#7 pare să fie din personal?' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Persoana #7, estompată' })).toBeInTheDocument();
    expect(screen.getByText('Se mișcă între mese · Sala')).toBeInTheDocument();
    expect(screen.queryByText(/scor/)).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Nu, #7 e client' }));
    expect(api.rejectSuggestion).toHaveBeenCalledWith('sug-1');
    await waitFor(() => expect(onResolved).toHaveBeenCalledWith('sug-1', 'rejected'));
    expect(screen.getByRole('button', { name: 'Da, #7 e din personal' })).toBeDisabled();
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

describe('RuleComposer examples', () => {
  const examples = ['Anunță-mă dacă un client ridică mâna', 'Anunță-mă dacă la intrare e coadă'];

  it('a chip fills the text; nothing is translated or saved until "Creează regula"', async () => {
    const user = userEvent.setup();
    const api = fakeApi({ draftRuleFromText: vi.fn(async () => ({ rule, explanation_ro: '' })) });
    renderWithApi(<RuleComposer cameraId="cam-sala" examples={examples} />, api);

    const chips = screen.getByRole('group', { name: 'Exemple' });
    await user.click(within(chips).getByRole('button', { name: examples[0] }));
    const input = screen.getByLabelText('Spune-i camerei ce să vadă');
    expect(input).toHaveValue(examples[0]);
    expect(input).toHaveFocus();
    expect(api.draftRuleFromText).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Creează regula' }));
    expect(api.draftRuleFromText).toHaveBeenCalledWith(examples[0], 'cam-sala');
    await screen.findByRole('region', { name: 'Ce am înțeles' });
    expect(api.createRule).not.toHaveBeenCalled();
  });

  it('a camera without rules shows the examples as a start list', async () => {
    const user = userEvent.setup();
    renderWithApi(<RuleComposer cameraId="cam-sala" examples={examples} startHere />);
    expect(screen.queryByRole('group', { name: 'Exemple' })).not.toBeInTheDocument();
    const start = screen.getByRole('group', { name: /Pornește de la un exemplu/ });
    await user.click(within(start).getByRole('button', { name: examples[1] }));
    expect(screen.getByLabelText('Spune-i camerei ce să vadă')).toHaveValue(examples[1]);
  });
});
