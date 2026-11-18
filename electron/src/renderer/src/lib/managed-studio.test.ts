import { expect, it } from 'vitest';
import { readStudioMode, studioWorkspaceUrl } from './managed-studio';

const workspaceId = 'a3f8e672-e26d-4ef3-8af8-c4525b72fd58';
const config = () => ({
  location: { origin: 'https://api.mancebo.ai' },
  __OMNIVOICE_API_BASE__: `https://api.mancebo.ai/studio/workspaces/${workspaceId}`,
  __MANCEBO_STUDIO__: { workspaceId, canOperate: true, platformAdmin: false },
});

it('leaves desktop and an ordinary web installation standalone without any Mancebo lookup', () => {
  expect(readStudioMode(false, config())).toEqual({ kind: 'standalone' });
  expect(readStudioMode(true, { location: { origin: 'https://my-studio.example' } })).toEqual({
    kind: 'standalone',
  });
  expect(readStudioMode(true)).toEqual({ kind: 'standalone' });
});

it('accepts only one canonical workspace at its exact Mancebo API boundary', () => {
  expect(readStudioMode(true, config())).toEqual({
    kind: 'managed',
    studio: { workspaceId, canOperate: true, platformAdmin: false },
  });
  const viewer = config();
  viewer.__MANCEBO_STUDIO__.canOperate = false;
  expect(readStudioMode(true, viewer)).toEqual({
    kind: 'managed',
    studio: { workspaceId, canOperate: false, platformAdmin: false },
  });
});

it.each([
  null,
  [],
  {},
  { workspaceId, canOperate: 'true', platformAdmin: false },
  { workspaceId: '../other', canOperate: true, platformAdmin: false },
  { workspaceId: workspaceId.toUpperCase(), canOperate: true, platformAdmin: false },
  { workspaceId: '00000000-0000-0000-0000-000000000000', canOperate: true, platformAdmin: false },
])('rejects malformed managed bootstrap without falling back to a key prompt: %j', (value) => {
  expect(readStudioMode(true, { ...config(), __MANCEBO_STUDIO__: value })).toEqual({
    kind: 'invalid',
  });
});

it('rejects foreign origins, different workspaces and user-selected upstream addresses', () => {
  for (const __OMNIVOICE_API_BASE__ of [
    'https://attacker.example',
    'https://api.mancebo.ai/studio/workspaces/other',
    `https://api.mancebo.ai/studio/workspaces/${workspaceId}?key=secret`,
  ]) {
    expect(readStudioMode(true, { ...config(), __OMNIVOICE_API_BASE__ })).toEqual({
      kind: 'invalid',
    });
  }
  expect(
    readStudioMode(true, { ...config(), location: { origin: 'https://attacker.example' } }),
  ).toEqual({ kind: 'invalid' });
});

it('returns a workspace navigation URL containing no key or session token', () => {
  expect(studioWorkspaceUrl({ workspaceId, canOperate: true, platformAdmin: false })).toBe(
    'https://mancebo.ai/voice-studio?business=' + workspaceId,
  );
  expect(studioWorkspaceUrl()).toBe('https://mancebo.ai/voice-studio');
});
