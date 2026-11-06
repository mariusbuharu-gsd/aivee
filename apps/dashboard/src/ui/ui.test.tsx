import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ConfirmDialog } from './Dialog';
import { Menu } from './Menu';
import { Select } from './Select';
import { Toaster } from './Toaster';
import { Segmented, Switch } from './controls';
import { TOAST_MS, useToast } from './toast';

const ROLES = [
  { value: 'manager', label: 'Manager', hint: 'reguli, camere, echipă' },
  { value: 'staff', label: 'Personal', hint: 'alerte și „Preiau”' },
] as const;
type R = (typeof ROLES)[number]['value'];

function RoleSelect({ onChange = vi.fn() }: { onChange?: (v: R) => void }) {
  const [v, setV] = useState<R>('staff');
  return (
    <Select
      label="Rol"
      value={v}
      options={[...ROLES]}
      onChange={(x) => {
        setV(x);
        onChange(x);
      }}
    />
  );
}

describe('Select', () => {
  it('opens a listbox, marks the current option and picks with the mouse', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<RoleSelect onChange={onChange} />);
    const box = screen.getByRole('combobox', { name: 'Rol' });
    expect(box).toHaveTextContent('Personal');
    await user.click(box);
    expect(screen.getByRole('option', { name: /Personal/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await user.click(screen.getByRole('option', { name: /Manager/ }));
    expect(onChange).toHaveBeenCalledWith('manager');
    expect(box).toHaveTextContent('Manager');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(box).toHaveFocus();
  });

  it('works from the keyboard and closes on Escape without changing', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<RoleSelect onChange={onChange} />);
    screen.getByRole('combobox', { name: 'Rol' }).focus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    await user.keyboard('{Enter}{ArrowUp}{Enter}');
    expect(onChange).toHaveBeenCalledWith('manager');
  });

  it('filters by typing when searchable', async () => {
    const user = userEvent.setup();
    render(
      <Select
        label="Cine"
        value=""
        searchable
        onChange={() => undefined}
        options={[
          { value: '', label: 'Oricine' },
          { value: 'u1', label: 'Mihai Ionescu' },
          { value: 'u2', label: 'Ana Dumitru' },
        ]}
      />,
    );
    await user.click(screen.getByRole('combobox', { name: 'Cine' }));
    await user.keyboard('ana');
    const list = screen.getByRole('listbox');
    expect(within(list).getAllByRole('option')).toHaveLength(1);
    await user.keyboard('zzz');
    expect(screen.getByText('Nimic găsit.')).toBeInTheDocument();
  });
});

describe('ConfirmDialog', () => {
  it('starts on "Renunță" and runs the action only on the verb button', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <ConfirmDialog
        title="O scoți pe Ana din echipă?"
        confirmLabel="Scoate-o din echipă"
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    );
    const dialog = screen.getByRole('dialog', { name: 'O scoți pe Ana din echipă?' });
    expect(within(dialog).getByRole('button', { name: 'Renunță' })).toHaveFocus();
    await user.click(within(dialog).getByRole('button', { name: 'Scoate-o din echipă' }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('asks for the exact name before deleting', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        title="Ștergi locația?"
        confirmLabel="Șterge locația"
        confirmText="Bistro Centru"
        onConfirm={onConfirm}
        onClose={() => undefined}
      />,
    );
    const go = screen.getByRole('button', { name: 'Șterge locația' });
    expect(go).toBeDisabled();
    await user.type(screen.getByLabelText(/ca să confirmi/), 'Bistro');
    expect(go).toBeDisabled();
    await user.type(screen.getByLabelText(/ca să confirmi/), ' Centru');
    expect(go).toBeEnabled();
    await user.click(go);
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it('stays open and shows why when the action fails', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <ConfirmDialog
        title="Ștergi regula?"
        confirmLabel="Șterge regula"
        onConfirm={() => Promise.reject(new Error('Serverul nu răspunde.'))}
        onClose={onClose}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Șterge regula' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Serverul nu răspunde.');
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe('Toaster', () => {
  afterEach(() => vi.useRealTimers());

  function Fire({ undo }: { undo?: () => void }) {
    const toast = useToast();
    return (
      <button
        onClick={() =>
          toast({
            kind: 'undo',
            title: 'Zona „Masa 2” a fost ștearsă',
            action: undo && { label: 'Anulează', run: undo },
          })
        }
      >
        fire
      </button>
    );
  }

  it('shows a toast with an undo action that runs once and closes it', async () => {
    const user = userEvent.setup();
    const undo = vi.fn();
    render(
      <Toaster>
        <Fire undo={undo} />
      </Toaster>,
    );
    await user.click(screen.getByRole('button', { name: 'fire' }));
    const region = screen.getByRole('region', { name: 'Notificări' });
    expect(region).toHaveTextContent('Zona „Masa 2” a fost ștearsă');
    await user.click(within(region).getByRole('button', { name: 'Anulează' }));
    expect(undo).toHaveBeenCalledOnce();
    expect(region).toBeEmptyDOMElement();
  });

  it('goes away by itself after a few seconds', () => {
    vi.useFakeTimers();
    render(
      <Toaster>
        <Fire />
      </Toaster>,
    );
    act(() => screen.getByRole('button', { name: 'fire' }).click());
    expect(screen.getByRole('status')).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(TOAST_MS + 50));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('Menu', () => {
  it('lists the safe actions first and the destructive one last', async () => {
    const user = userEvent.setup();
    const remove = vi.fn();
    render(
      <Menu
        label="Acțiuni pentru Mihai"
        items={[
          { label: 'Scoate din echipă…', onSelect: remove, danger: true },
          { label: 'Vezi în Istoric', onSelect: () => undefined },
        ]}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Acțiuni pentru Mihai' }));
    const items = screen.getAllByRole('menuitem');
    expect(items.map((i) => i.textContent)).toEqual(['Vezi în Istoric', 'Scoate din echipă…']);
    expect(items[0]).toHaveFocus();
    await user.keyboard('{ArrowDown}{Enter}');
    expect(remove).toHaveBeenCalledOnce();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
});

describe('Switch and Segmented', () => {
  it('toggle and report their value', async () => {
    const user = userEvent.setup();
    const onSwitch = vi.fn();
    const onSeg = vi.fn();
    render(
      <>
        <Switch checked label="Activă" onChange={onSwitch} />
        <Segmented
          label="Tip"
          value="table"
          onChange={onSeg}
          options={[
            { value: 'table', label: 'Masă' },
            { value: 'entrance', label: 'Intrare' },
          ]}
        />
      </>,
    );
    await user.click(screen.getByRole('switch', { name: 'Activă' }));
    expect(onSwitch).toHaveBeenCalledWith(false);
    expect(screen.getByRole('button', { name: 'Masă' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Intrare' }));
    expect(onSeg).toHaveBeenCalledWith('entrance');
  });
});
