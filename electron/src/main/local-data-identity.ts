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
  return (
    process.platform === 'win32' && SHARING.has((error as NodeJS.ErrnoException)?.code ?? '')
  );
}
const pause = () => new Promise((resolve) => setTimeout(resolve, 10));
// The publisher's Windows rename retry can take about 1.5 seconds. Readers and
// lock contenders share one larger, bounded deadline instead of abandoning a
// valid publication after 200/500 ms or multiplying nested retry budgets.
const CONTENTION_MS = 3000;
class IdentityAppeared extends Error {}
async function readSettled(path: string, deadline: number): Promise<Identity | null> {
  for (;;) {
    try {
      return await readIdentity(path);
    } catch (error) {
      if (performance.now() >= deadline || !(error instanceof IdentityAppeared || sharingViolation(error))) throw error;
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
    if (
      !info.isFile() ||
      !entry.isFile() ||
      info.dev !== entry.dev ||
      info.ino !== entry.ino ||
      info.size > BigInt(LIMIT)
    )
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
        // Another creator can publish after open observed ENOENT. Retry the
        // complete verified read, not the stale missing-file error. A dangling
        // link or other non-regular entry still fails without following it.
        if (entry.isFile()) throw new IdentityAppeared();
      } catch (missing) {
        if ((missing as NodeJS.ErrnoException).code === 'ENOENT') return null;
        throw missing;
      }
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
  try {
    const root = await stat(directory, { bigint: true });
    if (!root.isDirectory() || root.dev <= 0n || root.ino <= 0n) return;
    const dev = String(root.dev);
    const ino = String(root.ino);
    const sameRoot = async () => {
      const current = await stat(directory, { bigint: true });
      return current.isDirectory() && current.dev === root.dev && current.ino === root.ino;
    };
    const matches = (record: Identity | null) => record?.dev === dev && record.ino === ino;
    const deadline = performance.now() + CONTENTION_MS;
    const previous = await readSettled(path, deadline);
    if (matches(previous)) return (await sameRoot()) ? previous!.id : undefined;
    // One creator/rotation at a time. Other instances may read the completed
    // atomic publication; a stale or inaccessible lock simply leaves it unknown.
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
    if (!lock) return;
    const published = await readSettled(path, deadline);
    if (matches(published)) return (await sameRoot()) ? published!.id : undefined;
    const value: Identity = { version: 1, id: randomUUID(), dev, ino };
    temporary = `${path}.${randomUUID()}.tmp`;
    const output = await open(temporary, 'wx', 0o600);
    try {
      await output.writeFile(JSON.stringify(value), 'utf8');
      await output.sync();
    } finally {
      await output.close();
    }
    if (!(await sameRoot())) return;
    await renameWithRetry(temporary, path);
    temporary = undefined;
    return (await sameRoot()) ? value.id : undefined;
  } catch {
    return;
  } finally {
    if (temporary) await unlink(temporary).catch(() => {});
    if (lock) {
      await lock.close().catch(() => {});
      await unlink(lockPath).catch(() => {});
    }
  }
}
