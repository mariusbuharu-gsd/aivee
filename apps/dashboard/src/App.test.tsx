import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { App } from './App';
import { ApiContext } from './api/context';
import { MockApi } from './api/mock';
import { LiveDataProvider } from './state/LiveData';

function renderApp(path = '/') {
  const api = new MockApi({ latencyMs: 0, autoplay: false });
  render(
    <ApiContext.Provider value={api}>
      <MemoryRouter initialEntries={[path]}>
        <LiveDataProvider>
          <App />
        </LiveDataProvider>
      </MemoryRouter>
    </ApiContext.Provider>,
  );
  return api;
}

describe('App with the mock API', () => {
  it('shows cameras, the offline device and recent alerts on the live page', async () => {
    renderApp();
    expect(await screen.findByRole('article', { name: 'Camera Sala principală' })).toBeVisible();
    const terrace = screen.getByRole('article', { name: 'Camera Terasă' });
    expect(within(terrace).getByText('Dispozitiv offline')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Alerte recente' })).toBeInTheDocument();
    expect(await screen.findAllByText('Închisă')).toHaveLength(2);
    expect(screen.getAllByText(/angajat #7/).length).toBeGreaterThan(0);
  });

  it('navigates to the zone editor and lists the camera zones', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(
      await screen.findByRole('link', { name: 'Editează zonele pentru Sala principală' }),
    );
    expect(await screen.findByRole('heading', { name: /Zone \(3\)/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Masa 2/ }));
    expect(screen.getByLabelText('Nume')).toHaveValue('Masa 2');
    await user.click(screen.getByRole('button', { name: /Șterge/ }));
    expect(screen.getByRole('heading', { name: /Zone \(2\)/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Salvează zonele' })).toBeEnabled();
  });
});
