import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, type TelegramLink } from '../api/client';
import { MockAccounts, MOCK_PASSWORD, MOCK_TELEGRAM_CONNECT_MS } from '../api/mockAccounts';
import { fakeApi, renderWithApi } from '../test/fakeApi';
import { TelegramConnect } from './TelegramConnect';

const LINK: TelegramLink = {
  url: 'https://t.me/aivee_bot?startgroup=abc123def',
  private_url: 'https://t.me/aivee_bot?start=abc123def',
  expires_at: '2026-11-06T12:15:00Z',
};

function fakeTab() {
  return { opener: {}, location: { href: '' }, close: vi.fn() } as unknown as Window;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('TelegramConnect', () => {
  it('opens the link in a new tab and shows the connected group', async () => {
    const tab = fakeTab();
    const open = vi.spyOn(window, 'open').mockReturnValue(tab);
    const status = vi
      .fn()
      .mockResolvedValueOnce({ connected: false, chat_title: null }) // on mount
      .mockResolvedValueOnce({ connected: false, chat_title: null }) // first poll
      .mockResolvedValue({ connected: true, chat_title: 'Ospătari Terasa' });
    const onConnected = vi.fn();
    const api = fakeApi({
      createTelegramLink: vi.fn(async () => LINK),
      getTelegramStatus: status,
    });
    renderWithApi(<TelegramConnect locationId="demo" onConnected={onConnected} pollMs={5} />, api);

    await userEvent.click(screen.getByRole('button', { name: 'Conectează Telegram' }));
    expect(open).toHaveBeenCalledWith('about:blank', '_blank');
    expect(api.createTelegramLink).toHaveBeenCalledWith('demo');
    expect(tab.location.href).toBe(LINK.url);
    expect(tab.opener).toBeNull();
    expect(await screen.findByText('Aștept grupul din Telegram…')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Deschide Telegram' })).toHaveAttribute(
      'href',
      LINK.url,
    );
    expect(screen.getByRole('link', { name: /chat privat/ })).toHaveAttribute(
      'href',
      LINK.private_url,
    );

    expect(await screen.findByText('Conectat: Ospătari Terasa')).toBeInTheDocument();
    expect(onConnected).toHaveBeenCalledOnce();
    expect(screen.queryByText('Aștept grupul din Telegram…')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Conectează alt grup Telegram' })).toBeEnabled();
  });

  it('shows the current group on load', async () => {
    const api = fakeApi({
      getTelegramStatus: vi.fn(async () => ({ connected: true, chat_title: 'Bucătărie' })),
    });
    renderWithApi(<TelegramConnect locationId="demo" />, api);
    expect(await screen.findByText('Conectat: Bucătărie')).toBeInTheDocument();
  });

  it('gives a link to click when the popup was blocked', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    const api = fakeApi({ createTelegramLink: vi.fn(async () => LINK) });
    renderWithApi(<TelegramConnect locationId="demo" pollMs={1000} />, api);
    await userEvent.click(screen.getByRole('button', { name: 'Conectează Telegram' }));
    expect(await screen.findByText(/Deschide linkul de mai jos/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Deschide Telegram' })).toBeInTheDocument();
  });

  it('stops waiting after the deadline', async () => {
    vi.spyOn(window, 'open').mockReturnValue(fakeTab());
    const api = fakeApi({ createTelegramLink: vi.fn(async () => LINK) });
    renderWithApi(<TelegramConnect locationId="demo" pollMs={5} waitMs={20} />, api);
    await userEvent.click(screen.getByRole('button', { name: 'Conectează Telegram' }));
    expect(await screen.findByText('Linkul a expirat')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Conectează Telegram' })).toBeEnabled();
  });

  it('shows the server error and closes the blank tab', async () => {
    const tab = fakeTab();
    vi.spyOn(window, 'open').mockReturnValue(tab);
    const api = fakeApi({
      createTelegramLink: vi.fn(async () => {
        throw new ApiError('Botul Telegram nu este configurat pe server.', 'unavailable', 503);
      }),
    });
    renderWithApi(<TelegramConnect locationId="demo" />, api);
    await userEvent.click(screen.getByRole('button', { name: 'Conectează Telegram' }));
    expect(await screen.findByText('Botul Telegram nu este configurat pe server.')).toBeVisible();
    expect(tab.close).toHaveBeenCalled();
  });
});

describe('mock Telegram link', () => {
  it('connects the location after a while, once', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-11-06T12:00:00Z'));
    const accounts = new MockAccounts(
      () => [],
      (z) => z,
      () => undefined,
    );
    accounts.login('owner@aivee.demo', MOCK_PASSWORD);
    const link = accounts.createTelegramLink('demo');
    expect(link.url).toMatch(/^https:\/\/t\.me\/aivee_demo_bot\?startgroup=/);
    expect(link.private_url).toMatch(/\?start=/);
    expect(accounts.getTelegramStatus('demo').connected).toBe(false);
    vi.setSystemTime(Date.now() + MOCK_TELEGRAM_CONNECT_MS);
    await waitFor(() =>
      expect(accounts.getTelegramStatus('demo')).toEqual({
        connected: true,
        chat_title: 'Echipa Terasa demo',
      }),
    );
    expect(accounts.listAudit({ location_id: 'demo' }).items[0]?.kind).toBe(
      'location.telegram_connected',
    );
  });

  it('needs locations.manage', () => {
    const accounts = new MockAccounts(
      () => [],
      (z) => z,
      () => undefined,
    );
    accounts.login('manager@aivee.demo', MOCK_PASSWORD);
    expect(() => accounts.createTelegramLink('demo')).toThrow();
  });
});
