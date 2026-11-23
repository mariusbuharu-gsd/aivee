import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  type ApiClient,
  type Capabilities,
  type CameraView,
  type DiscoveredCamera,
} from '../api/client';
import { CapabilitiesContext } from '../state/capabilitiesContext';
import { fakeApi, renderWithApi } from '../test/fakeApi';
import { AddCamera } from './AddCameraWizard';
import { TestCameraDialog } from './TestCameraDialog';

const ALL: Capabilities = { videos: true, enrol: true, camera_test: true, camera_discovery: true };

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
const hik: DiscoveredCamera = {
  ...tapo,
  ip: '192.168.1.31',
  brand: 'hikvision',
  model: 'DS-2CD1043G2-I',
  rtsp_paths: ['/Streaming/Channels/102'],
};
const added: DiscoveredCamera = { ...tapo, ip: '192.168.1.20', model: 'C200', already_added: true };

const sala: CameraView = {
  id: 'cam-sala',
  name: 'Sala',
  source: 'rtsp://u:p@192.168.1.20:554/stream2',
  device: 'edge-a',
  online: true,
  zones: [],
};

function setup(overrides: Partial<ApiClient> = {}, caps: Capabilities = ALL) {
  const api = fakeApi({
    listDevices: vi.fn(async () => [{ device: 'edge-a', state: 'online' as const }]),
    discoverCameras: vi.fn(async () => [added, tapo, hik]),
    ...overrides,
  });
  const onCreated = vi.fn();
  renderWithApi(
    <CapabilitiesContext.Provider value={caps}>
      <AddCamera cameras={[sala]} onCreated={onCreated} defaultId="cam-01" />
    </CapabilitiesContext.Provider>,
    api,
  );
  return { api, onCreated, user: userEvent.setup() };
}

describe('AddCamera wizard', () => {
  it('finds cameras on the one online box, then tests and saves the picked one', async () => {
    const { api, onCreated, user } = setup();
    await user.click(await screen.findByRole('button', { name: 'Caută camere' }));
    expect(api.discoverCameras).toHaveBeenCalledWith('edge-a');
    const list = await screen.findByRole('list', { name: 'Camere găsite' });
    const taken = within(list).getByRole('button', { name: /Tapo C200/ });
    expect(taken).toBeDisabled();
    expect(taken).toHaveTextContent('Deja adăugată');

    await user.click(within(list).getByRole('button', { name: /Hikvision/ }));
    expect(screen.getByLabelText('Utilizator')).toHaveValue('admin');
    expect(
      screen.getByText('Folosește utilizatorul și parola de admin ale camerei.'),
    ).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Continuă' })).toBeNull();
    await user.type(screen.getByLabelText('Parolă'), 's3cret');
    await user.click(screen.getByRole('button', { name: 'Testează' }));
    expect(api.testCamera).toHaveBeenCalledWith({
      source: 'rtsp://admin:s3cret@192.168.1.31:554/Streaming/Channels/102',
      device: 'edge-a',
    });
    expect(await screen.findByRole('img', { name: /Imagine de test/ })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Continuă' }));
    await user.type(screen.getByLabelText('Numele camerei'), 'Sala mare');
    await user.click(screen.getByRole('button', { name: 'Salvează camera' }));
    expect(api.createCamera).toHaveBeenCalledWith({
      id: 'cam-sala-mare',
      name: 'Sala mare',
      source: 'rtsp://admin:s3cret@192.168.1.31:554/Streaming/Channels/102',
      device: 'edge-a',
    });
    expect(onCreated).toHaveBeenCalled();
    // Never the address, the id or the box in the owner path.
    expect(document.body).not.toHaveTextContent('rtsp://');
    expect(document.body).not.toHaveTextContent('edge-a');
    expect(document.body).not.toHaveTextContent('s3cret');
  });

  it('opens the Tapo guide when a Tapo camera refuses the password', async () => {
    const { user } = setup({
      testCamera: vi.fn(async () => {
        throw new ApiError('Camera a refuzat parola.', 'camera_auth', 422);
      }),
    });
    await user.click(await screen.findByRole('button', { name: 'Caută camere' }));
    await user.click(await screen.findByRole('button', { name: /Tapo C210/ }));
    expect(screen.getByLabelText('Utilizator')).toHaveValue('');
    const guide = screen.getByText(/Cum faci contul camerei/).closest('details');
    expect(guide).not.toHaveAttribute('open');
    await user.type(screen.getByLabelText('Utilizator'), 'ana');
    await user.type(screen.getByLabelText('Parolă'), 'gresit');
    await user.click(screen.getByRole('button', { name: 'Testează' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Camera a refuzat parola.');
    expect(alert).toHaveTextContent(/nu contul tău Tapo/);
    expect(guide).toHaveAttribute('open');
    expect(screen.getByText(/Third-Party Compatibility/)).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Continuă' })).toBeNull();
  });

  it('explains what to check when no box is online', async () => {
    const { api, user } = setup({
      listDevices: vi.fn(async () => [{ device: 'edge-a', state: 'offline' as const }]),
    });
    expect(
      await screen.findByRole('heading', { name: 'Cutia AiVee nu e pornită sau nu e conectată' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/lumina aprinsă/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Verifică din nou' }));
    expect(api.listDevices).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('button', { name: 'Caută camere' })).toBeNull();
  });

  it('lets the owner pick one of several boxes, named by the cameras they serve', async () => {
    const { api, user } = setup({
      listDevices: vi.fn(async () => [
        { device: 'edge-a', state: 'online' as const },
        { device: 'edge-b', state: 'online' as const },
      ]),
    });
    expect(await screen.findByRole('button', { name: /Cutia AiVee 1.*Sala/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Cutia AiVee 2/ }));
    await user.click(screen.getByRole('button', { name: 'Caută camere' }));
    expect(api.discoverCameras).toHaveBeenCalledWith('edge-b');
    expect(document.body).not.toHaveTextContent('edge-b');
  });

  it('shows the box problem when the scan fails, and can try again', async () => {
    const discover = vi
      .fn<ApiClient['discoverCameras']>()
      .mockRejectedValueOnce(new ApiError('Cutia nu a răspuns la timp.', 'device_timeout', 504))
      .mockResolvedValueOnce([]);
    const { user } = setup({ discoverCameras: discover });
    await user.click(await screen.findByRole('button', { name: 'Caută camere' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Cutia nu a răspuns la timp.');
    await user.click(screen.getByRole('button', { name: 'Caută din nou' }));
    expect(await screen.findByText('Nu am găsit nicio cameră.')).toBeInTheDocument();
  });

  it('switches to the manual brand + IP form and back', async () => {
    const { user } = setup();
    await user.click(await screen.findByRole('button', { name: 'Adaug-o manual' }));
    expect(screen.getByLabelText('Adresa IP')).toBeInTheDocument();
    expect(screen.getByLabelText('Dispozitiv')).toHaveValue('edge-a');
    await user.click(screen.getByRole('button', { name: /Înapoi la „Caută camere”/ }));
    expect(await screen.findByRole('button', { name: 'Caută camere' })).toBeInTheDocument();
  });

  it('keeps the manual form while the server cannot look for cameras', () => {
    setup({}, { videos: true, enrol: true, camera_test: true });
    expect(screen.getByLabelText('Adresa IP')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Caută camere' })).toBeNull();
  });
});

describe('TestCameraDialog', () => {
  it('tests a saved camera by id and shows the still', async () => {
    const api = fakeApi();
    renderWithApi(<TestCameraDialog camera={sala} onClose={() => undefined} />, api);
    expect(await screen.findByRole('img', { name: /Imagine de test/ })).toBeInTheDocument();
    expect(api.testCamera).toHaveBeenCalledWith({ camera_id: 'cam-sala' });
  });

  it('points to "Editează camera" and the Tapo guide on a refused password', async () => {
    const api = fakeApi({
      testCamera: vi.fn(async () => {
        throw new ApiError('', 'camera_auth', 422);
      }),
    });
    renderWithApi(<TestCameraDialog camera={sala} onClose={() => undefined} />, api);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Camera a refuzat utilizatorul sau parola.');
    expect(alert).toHaveTextContent(/Editează camera/);
    expect(screen.getByText(/Cum faci contul camerei/).closest('details')).toHaveAttribute('open');
  });
});
