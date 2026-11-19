/** Isolated compiled-web acceptance. Every network request is fulfilled locally. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, mkdir } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { execFileSync } from 'node:child_process';
import { chromium } from 'playwright';

const root = resolve(import.meta.dirname, '../..');
const dist = resolve(root, 'frontend/dist');
const git = execFileSync('git', ['rev-parse', '--git-dir'], { cwd: root, encoding: 'utf8' }).trim();
const evidence = resolve(root, git, 'testagent/managed-browser');
await mkdir(evidence, { recursive: true });
const workspace = 'a3f8e672-e26d-4ef3-8af8-c4525b72fd58';
const prefix = `/studio/workspaces/${workspace}`;
const origin = 'https://api.mancebo.ai';
const bootstrap = `window.__OMNIVOICE_API_BASE__=${JSON.stringify(origin+prefix)};window.__MANCEBO_STUDIO__=${JSON.stringify({workspaceId:workspace,canOperate:true,platformAdmin:false})};`;
const hash = createHash('sha256').update(bootstrap).digest('base64');
const html = (await readFile(resolve(dist, 'index.html'), 'utf8'))
  .replace("script-src 'self'", `script-src 'self' 'sha256-${hash}'`)
  .replace('<head>', `<head><script>${bootstrap}</script>`);
const types = { '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.json': 'application/json', '.webp': 'image/webp', '.woff2': 'font/woff2' };
const browser = await chromium.launch({ headless: true });
let assertions = 0;
try {
  for (const width of [1440,390,320]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, locale: 'en-US', colorScheme: 'light' });
    const page = await context.newPage();
    const requests = [];
    let release;
    const responseReady = new Promise((done) => { release = done; });
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      requests.push({ origin: url.origin, path: url.pathname });
      if (url.origin !== origin) return route.abort('blockedbyclient');
      if (url.pathname === prefix+'/' && route.request().resourceType() === 'document') {
        return route.fulfill({ status: 200, contentType: 'text/html', body: html });
      }
      if (url.pathname === prefix+'/mancebo/session') {
        await responseReady;
        return route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({detail:'Current Mancebo session expired'}) });
      }
      if (url.pathname.startsWith('/studio/static/')) {
        const target = resolve(dist, decodeURIComponent(url.pathname.slice('/studio/static/'.length)));
        assert.ok(target.startsWith(dist+sep), 'Static fixture stays within the compiled output');
        try { return route.fulfill({ status: 200, contentType: types[extname(target)] || 'application/octet-stream', body: await readFile(target) }); }
        catch { return route.fulfill({ status: 404, body: 'Missing local fixture asset' }); }
      }
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
    });
    await page.goto(origin+prefix+'/', { waitUntil: 'domcontentloaded' });
    await page.getByRole('status').filter({hasText:'Loading'}).waitFor();
    assert.equal(await page.locator('input').count(), 0, 'Loading never asks for a provider credential'); assertions++;
    await page.screenshot({ path: resolve(evidence, `loading-${width}.png`), fullPage: true });
    release();
    await page.getByRole('heading', { name: 'Your studio session has ended. Reconnect from your Mancebo workspace.' }).waitFor(); assertions++;
    const link = page.getByRole('link', { name: 'Open my Mancebo workspace' });
    assert.equal(await link.getAttribute('href'), `https://mancebo.ai/voice-studio?business=${workspace}`); assertions++;
    assert.equal(await page.locator('input').count(), 0, 'Expired managed sessions have no key or PIN form'); assertions++;
    await link.focus();
    assert.equal(await link.evaluate(element => element === document.activeElement), true); assertions++;
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false); assertions++;
    assert.ok((await page.title()).includes('Mancebo.ai')); assertions++;
    assert.equal(requests.some(request => request.origin !== origin), false, 'No request reaches Mancebo production or third parties'); assertions++;
    assert.equal(requests.some(request => request.path.includes('/api/auth/session')), false); assertions++;
    await page.screenshot({ path: resolve(evidence, `expired-${width}.png`), fullPage: true });
    await context.close();
  }
  console.log(JSON.stringify({ assertions, widths:[1440,390,320], evidence, productionRequests:0 }));
} finally { await browser.close(); }
