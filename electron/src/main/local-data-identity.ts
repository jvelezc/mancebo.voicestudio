import { constants } from 'node:fs';
import { lstat, open, stat, unlink } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import { renameWithRetry } from './rename-retry';

const FILE = '.voicestudio-data-identity.json';
const LIMIT = 1024;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
// On Windows a file being deleted or replaced stays "delete pending" until every
// handle closes, so a racing open fails with EPERM/EACCES/EBUSY instead of
// EEXIST/ENOENT. Those are contention there, not failure.
const SHARING = new Set(['EPERM', 'EACCES', 'EBUSY']);
function sharingViolation(error: unknown): boolean {
  return process.platform === 'win32' && SHARING.has((error as NodeJS.ErrnoException)?.code ?? '');
}
/** Failure record for diagnosis: a stage and an error code, never a path or content. */
export interface IdentityFailure {
  stage: string;
  code: string;
}
const failures: IdentityFailure[] = [];
function record(stage: string, error: unknown): void {
  const code = (error as NodeJS.ErrnoException)?.code;
  failures.push({ stage, code: typeof code === 'string' ? code : 'UNKNOWN' });
  if (failures.length > 16) failures.shift();
}
/** Recent failures (oldest first), for tests and support diagnostics. */
export function localDataIdentityFailures(): readonly IdentityFailure[] {
  return failures.slice();
}
export function resetLocalDataIdentityFailures(): void {
  failures.length = 0;
}
/** A read that raced a concurrent publication; re-reading settles it. */
function racing(): Error {
  return Object.assign(new Error('Identity changed during read'), { code: 'RACING' });
}
const pause = () => new Promise((resolve) => setTimeout(resolve, 10));
// The publisher's Windows rename retry can take about 1.5 seconds. Readers and
// lock contenders share one larger, bounded deadline instead of abandoning a
// valid publication after 200/500 ms or multiplying nested retry budgets.
const CONTENTION_MS = 3000;
async function readSettled(path: string, deadline: number): Promise<Identity | null> {
  for (;;) {
    try {
      return await readIdentity(path);
    } catch (error) {
      const transient =
        sharingViolation(error) || (error as NodeJS.ErrnoException)?.code === 'RACING';
      if (performance.now() >= deadline || !transient) throw error;
      await pause();
    }
  }
}
interface Identity {
  version: 1;
  id: string;
  dev: string;
  ino: string;
}
async function readIdentity(path: string): Promise<Identity | null> {
  let file;
  try {
    file = await open(
      path,
      constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0),
    );
    const info = await file.stat({ bigint: true });
    const entry = await lstat(path, { bigint: true });
    // Two regular files with different ids: the entry was replaced between our
    // open and lstat (a concurrent publication). Not a link, so re-read it; a
    // symlink or directory fails the isFile checks below and stays an error.
    if (info.isFile() && entry.isFile() && (info.dev !== entry.dev || info.ino !== entry.ino))
      throw racing();
    if (!info.isFile() || !entry.isFile() || info.size > BigInt(LIMIT))
      throw new Error('Unusable identity');
    const buffer = Buffer.alloc(LIMIT + 1);
    const { bytesRead } = await file.read(buffer, 0, buffer.length, 0);
    if (bytesRead > LIMIT) throw new Error('Oversized identity');
    const value = JSON.parse(buffer.subarray(0, bytesRead).toString('utf8')) as Identity;
    if (
      value.version !== 1 ||
      typeof value.id !== 'string' ||
      !UUID.test(value.id) ||
      typeof value.dev !== 'string' ||
      typeof value.ino !== 'string' ||
      !/^[1-9]\d*$/.test(value.dev) ||
      !/^[1-9]\d*$/.test(value.ino)
    )
      throw new Error('Invalid identity');
    return value;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      // A dangling link is present, not an absent metadata file.
      try {
        const entry = await lstat(path);
        if (!entry.isFile()) throw new Error('Unusable identity');
      } catch (missing) {
        if ((missing as NodeJS.ErrnoException).code === 'ENOENT') return null;
        throw missing;
      }
      // Published between our open and lstat: a creator won the race. Re-read.
      throw racing();
    }
    throw error;
  } finally {
    await file?.close();
  }
}

/** Opaque identity for a caller-proven local data root; never creates the root.
 * The directory inode keeps aliases/renames stable and makes copied metadata
 * acquire a different identity. Failure is unknown, never a path-derived ID.
 */
export async function localDataIdentity(directory: string): Promise<string | undefined> {
  const path = join(directory, FILE);
  const lockPath = `${path}.lock`;
  let lock;
  let temporary: string | undefined;
  let stage = 'root';
  try {
    const root = await stat(directory, { bigint: true });
    if (!root.isDirectory() || root.dev <= 0n || root.ino <= 0n) {
      record('root', { code: 'UNUSABLE_ROOT' });
      return;
    }
    const dev = String(root.dev);
    const ino = String(root.ino);
    const sameRoot = async () => {
      const current = await stat(directory, { bigint: true });
      return current.isDirectory() && current.dev === root.dev && current.ino === root.ino;
    };
    const matches = (record: Identity | null) => record?.dev === dev && record.ino === ino;
    const deadline = performance.now() + CONTENTION_MS;
    stage = 'read';
    const previous = await readSettled(path, deadline);
    if (matches(previous)) return (await sameRoot()) ? previous!.id : undefined;
    // One creator/rotation at a time. Other instances may read the completed
    // atomic publication; a stale or inaccessible lock simply leaves it unknown.
    stage = 'lock';
    while (performance.now() < deadline) {
      try {
        lock = await open(lockPath, 'wx', 0o600);
        break;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'EEXIST' && !sharingViolation(error))
          throw error;
        await pause();
        const published = await readSettled(path, deadline);
        if (matches(published)) return (await sameRoot()) ? published!.id : undefined;
      }
    }
    if (!lock) {
      record('lock', { code: 'TIMEOUT' });
      return;
    }
    stage = 'read-locked';
    const published = await readSettled(path, deadline);
    if (matches(published)) return (await sameRoot()) ? published!.id : undefined;
    stage = 'write';
    const value: Identity = { version: 1, id: randomUUID(), dev, ino };
    temporary = `${path}.${randomUUID()}.tmp`;
    const output = await open(temporary, 'wx', 0o600);
    try {
      await output.writeFile(JSON.stringify(value), 'utf8');
      await output.sync();
    } finally {
      await output.close();
    }
    if (!(await sameRoot())) {
      record('write', { code: 'ROOT_CHANGED' });
      return;
    }
    stage = 'rename';
    await renameWithRetry(temporary, path);
    temporary = undefined;
    stage = 'verify';
    return (await sameRoot()) ? value.id : undefined;
  } catch (error) {
    record(stage, error);
    return;
  } finally {
    if (temporary) await unlink(temporary).catch(() => {});
    if (lock) {
      await lock.close().catch(() => {});
      await unlink(lockPath).catch(() => {});
    }
  }
}
