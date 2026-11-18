import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const workspaceId = 'a3f8e672-e26d-4ef3-8af8-c4525b72fd58';
const mocks = vi.hoisted(() => ({ fetch: vi.fn(), reconnect: vi.fn(), mode: vi.fn() }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/lib/managed-studio', async (original) => ({
  ...(await original<typeof import('@/lib/managed-studio')>()),
  studioMode: mocks.mode,
  requestStudioReconnect: mocks.reconnect,
}));
vi.mock('@/lib/api/client', async (original) => ({
  ...(await original<typeof import('@/lib/api/client')>()),
  apiFetch: mocks.fetch,
}));

import { ApiError } from '@/lib/api/client';
import { WebAuthGate } from './web-auth-gate';

beforeEach(() => {
  mocks.fetch.mockReset();
  mocks.reconnect.mockReset();
  mocks.mode.mockReturnValue({
    kind: 'managed',
    studio: { workspaceId, canOperate: true, platformAdmin: false },
  });
});
afterEach(cleanup);
const mount = () =>
  render(
    <WebAuthGate>
      <h1>My studio project</h1>
    </WebAuthGate>,
  );
const response = (value: unknown) =>
  new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });

it('opens the native studio only after the current workspace reports execution ready', async () => {
  mocks.fetch.mockResolvedValue(response({ workspace_id: workspaceId, execution_available: true }));
  mount();
  expect(await screen.findByRole('heading', { name: 'My studio project' })).toBeVisible();
  expect(mocks.fetch).toHaveBeenCalledExactlyOnceWith('/mancebo/session');
  expect(mocks.reconnect).not.toHaveBeenCalled();
  expect(screen.queryByLabelText('settings.remote_backend_key')).not.toBeInTheDocument();
});

it.each([
  { workspace_id: workspaceId, execution_available: false },
  { workspace_id: '3aa624fa-9a72-4eb4-8644-2696f5a1ac03', execution_available: true },
  {},
  null,
])(
  'does not mistake a healthy response or a foreign workspace for ready execution: %j',
  async (body) => {
    mocks.fetch.mockResolvedValue(response(body));
    mount();
    expect(await screen.findByRole('heading', { name: 'managedStudio.unavailable' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'My studio project' })).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  },
);

it('offers a key-free workspace recovery path after membership or session access ends', async () => {
  mocks.fetch.mockRejectedValue(new ApiError(401, 'Current session expired'));
  mount();
  expect(
    await screen.findByRole('heading', { name: 'managedStudio.sessionExpired' }),
  ).toBeVisible();
  const link = screen.getByRole('link', { name: 'managedStudio.openWorkspace' });
  expect(link).toHaveAttribute('href', 'https://mancebo.ai/voice-studio?business=' + workspaceId);
  expect(link).toHaveAttribute('target', '_top');
  expect(document.querySelector('input')).toBeNull();
  expect(mocks.reconnect).toHaveBeenCalledTimes(1);
  act(() => {
    window.dispatchEvent(new Event('ov:auth-required'));
    window.dispatchEvent(new Event('ov:auth-required'));
  });
  expect(mocks.reconnect).toHaveBeenCalledTimes(1);
});

it('an expiry event wins over an older in-flight successful session check', async () => {
  let resolve!: (value: Response) => void;
  mocks.fetch.mockReturnValue(
    new Promise<Response>((done) => {
      resolve = done;
    }),
  );
  mount();
  expect(screen.getByRole('status')).toHaveTextContent('preferences.loading');
  act(() => {
    window.dispatchEvent(new Event('ov:auth-required'));
  });
  await act(async () => {
    resolve(response({ workspace_id: workspaceId, execution_available: true }));
  });
  expect(screen.getByRole('heading', { name: 'managedStudio.sessionExpired' })).toBeVisible();
  expect(screen.queryByRole('heading', { name: 'My studio project' })).not.toBeInTheDocument();
  expect(mocks.reconnect).toHaveBeenCalledTimes(1);
});

it('lets the customer retry a service outage without exchanging or saving a key', async () => {
  mocks.fetch.mockRejectedValueOnce(new ApiError(503, 'Service unavailable'));
  mocks.fetch.mockResolvedValueOnce(
    response({ workspace_id: workspaceId, execution_available: true }),
  );
  mount();
  expect(await screen.findByRole('heading', { name: 'managedStudio.unavailable' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'managedStudio.retry' }));
  expect(await screen.findByRole('heading', { name: 'My studio project' })).toBeVisible();
  expect(mocks.fetch).toHaveBeenCalledTimes(2);
  expect(mocks.reconnect).not.toHaveBeenCalled();
});

it('does not perform a lookup or reveal the standalone key form for invalid managed bootstrap', async () => {
  mocks.mode.mockReturnValue({ kind: 'invalid' });
  mount();
  expect(await screen.findByRole('heading', { name: 'managedStudio.unavailable' })).toBeVisible();
  expect(mocks.fetch).not.toHaveBeenCalled();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
  expect(document.querySelector('input')).toBeNull();
});

it('keeps ordinary desktop behavior and makes no Mancebo session lookup', () => {
  mocks.mode.mockReturnValue({ kind: 'standalone' });
  mount();
  expect(screen.getByRole('heading', { name: 'My studio project' })).toBeVisible();
  expect(mocks.fetch).not.toHaveBeenCalled();
});
