// @vitest-environment node
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { mkdir, mkdtemp, rename, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// Windows reports a racing open of a file another creator is deleting or
// replacing ("delete pending") as EPERM, not EEXIST/ENOENT. Simulate one such
// refusal per matching path and check the identity is still found, not unknown.
const refuse = vi.hoisted(() => ({ suffixes: new Set<string>(), appeared: null as { path: string; contents: string } | null }));
vi.mock('node:fs/promises', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs/promises')>();
  return {
    ...actual,
    open: (async (path: string, ...rest: unknown[]) => {
      if (refuse.appeared?.path === String(path)) {
        const publication = refuse.appeared;
        refuse.appeared = null;
        await actual.writeFile(publication.path, publication.contents);
        // The caller's open saw absence before this other creator published;
        // its subsequent lstat now sees the complete regular metadata file.
        throw Object.assign(new Error('ENOENT during publication'), { code: 'ENOENT' });
      }
      for (const suffix of refuse.suffixes)
        if (String(path).endsWith(suffix)) {
          refuse.suffixes.delete(suffix);
          throw Object.assign(new Error('EPERM: operation not permitted'), { code: 'EPERM' });
        }
      return (actual.open as (...args: unknown[]) => unknown)(path, ...rest);
    }) as typeof actual.open,
  };
});

import { localDataIdentity } from './local-data-identity';

const FILE = '.voicestudio-data-identity.json';
const platform = Object.getOwnPropertyDescriptor(process, 'platform')!;
let root: string;
beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), 'vs-identity-win-'));
  Object.defineProperty(process, 'platform', { value: 'win32' });
});
afterEach(async () => {
  Object.defineProperty(process, 'platform', platform);
  refuse.suffixes.clear();
  refuse.appeared = null;
  await rm(root, { recursive: true, force: true });
});

it('retries a lock another creator is still deleting on Windows', async () => {
  const directory = join(root, 'data');
  await mkdir(directory);
  refuse.suffixes.add(`${FILE}.lock`);
  const id = await localDataIdentity(directory);
  expect(id).toMatch(/^[0-9a-f-]{36}$/);
  expect(await localDataIdentity(directory)).toBe(id);
});

it('waits for a concurrent publisher through the existing Windows rename retry window', async () => {
  const directory = join(root, 'data');
  await mkdir(directory);
  const info = await stat(directory, { bigint: true });
  const path = join(directory, FILE);
  const lock = `${path}.lock`;
  const expected = '12345678-1234-4234-8234-123456789abc';
  await writeFile(lock, 'another creator owns this lock');
  const identity = localDataIdentity(directory);
  const publish = (async () => {
    // FILE_RENAME can legitimately retry for about 1.5 seconds on Windows;
    // the old 500 ms identity lock budget abandoned an otherwise valid writer.
    await new Promise(resolve => setTimeout(resolve, 1800));
    const temporary = `${path}.published.tmp`;
    await writeFile(temporary, JSON.stringify({ version: 1, id: expected, dev: String(info.dev), ino: String(info.ino) }));
    await rename(temporary, path);
    await rm(lock);
  })();
  const [actual] = await Promise.all([identity, publish]);
  expect(actual).toBe(expected);
  expect(await localDataIdentity(directory)).toBe(expected);
});

it('retries an identity file another creator is still replacing on Windows', async () => {
  const directory = join(root, 'data');
  await mkdir(directory);
  const id = await localDataIdentity(directory);
  refuse.suffixes.add(FILE);
  expect(await localDataIdentity(directory)).toBe(id);
});

it('reads the identity that appears between a missing open and its existence check', async () => {
  const directory = join(root, 'data');
  await mkdir(directory);
  const info = await stat(directory, { bigint: true });
  const expected = '87654321-4321-4321-8321-cba987654321';
  refuse.appeared = { path: join(directory, FILE), contents: JSON.stringify({
    version: 1, id: expected, dev: String(info.dev), ino: String(info.ino),
  }) };
  expect(await localDataIdentity(directory)).toBe(expected);
  expect(await localDataIdentity(directory)).toBe(expected);
});

it('keeps a non-Windows EPERM a failure, never a guessed identity', async () => {
  Object.defineProperty(process, 'platform', { value: 'linux' });
  const directory = join(root, 'data');
  await mkdir(directory);
  await writeFile(join(directory, 'placeholder'), '');
  refuse.suffixes.add(`${FILE}.lock`);
  expect(await localDataIdentity(directory)).toBeUndefined();
});
