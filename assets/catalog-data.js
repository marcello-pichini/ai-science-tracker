/* Validate the exact bytes used by every view against one public component manifest. */
globalThis.AST_t ||= (en, vars) => {
  const table = globalThis.AST_MESSAGES;
  let s = table && Object.prototype.hasOwnProperty.call(table, en) && typeof table[en] === 'string' ? table[en] : en;
  if (vars) for (const key of Object.keys(vars)) s = s.split('{' + key + '}').join(String(vars[key]));
  return s;
};
(() => {
  // Keep this binding inside the module. A top-level const would clash with the
  // homepage script, which also declares tr, and that script would not run.
  const tr = globalThis.AST_t;
  const script = typeof document === 'undefined' ? null : document.currentScript;
  const defaultRoot = script ? new URL('../', script.src).href : 'https://aisciencetracker.org/';
  let sequence = 0;
  const hex = bytes => Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
  function validateManifest(value) {
    if (value?.schema_version !== 1 || !/^[a-f0-9]{64}$/.test(value.snapshot_sha256) || !value.components || typeof value.components !== 'object') throw Error('Invalid component manifest');
    for (const c of Object.values(value.components)) {
      if (!/^data\/(?:benchmarks\/)?[a-z0-9-]+\.(json|csv)$/.test(c.path) || !/^[a-f0-9]{64}$/.test(c.sha256) || !Number.isSafeInteger(c.bytes) || c.bytes < 0) throw Error('Invalid component descriptor');
    }
    return value;
  }
  function validateData(id, value) {
    const arrays = ['discoveries', 'discoveries-list', 'archived-discoveries', 'vulnerabilities-preview'];
    if (arrays.includes(id) && !Array.isArray(value)) throw Error('Invalid record collection');
    if (['models','model-progress'].includes(id) && !Array.isArray(value?.models)) throw Error('Invalid model collection');
    if (id === 'models' && !Array.isArray(value.families)) throw Error('Invalid model families');
    if (id === 'swe-bench' && !Array.isArray(value?.records)) throw Error('Invalid evaluation collection');
    if (id === 'benchmark-registry' && !Array.isArray(value?.sources)) throw Error('Invalid benchmark registry');
    if (id.startsWith('benchmark-') && id !== 'benchmark-registry' && !Array.isArray(value?.records)) throw Error('Invalid benchmark observations');
    if (id === 'citations' && (!value?.records || typeof value.records !== 'object')) throw Error('Invalid citation collection');
    if (id === 'entity-aliases' && (!Array.isArray(value?.organizations) || !Array.isArray(value?.systems))) throw Error('Invalid entity map');
  }
  async function load(ids, options = {}) {
    const root = new URL(options.root || defaultRoot);
    const fetcher = options.fetch || globalThis.fetch;
    const request = async (url, init, read, bytes = 0) => {
      const controller = new AbortController();
      // Large components get more time, so a slow connection finishes instead of failing twice.
      const timeout = setTimeout(() => controller.abort(), 12000 + bytes / 100);
      try {return await read(await fetcher(url, {...init, signal:controller.signal}));}
      finally {clearTimeout(timeout);}
    };
    const cryptoAPI = options.crypto || globalThis.crypto;
    if (!cryptoAPI?.subtle) throw Error('Secure SHA-256 is unavailable. Open the HTTPS site or localhost.');
    const notify = state => options.onState?.(state);
    const manifest = async () => {
      const url = new URL('api/v1/manifest.json', root);
      url.searchParams.set('load', Date.now().toString(36) + '-' + (++sequence));
      return request(url.href, {cache:'no-store'}, async r => {
        if (!r.ok) throw Error('Component manifest unavailable');
        return validateManifest(await r.json());
      });
    };
    let error;
    for (let attempt = 0; attempt < 2; attempt++) {
      notify(attempt ? 'retrying' : 'loading');
      try {
        const before = await manifest();
        const grouped = (options.groups || []).flatMap(group => {
          const members = Object.keys(before.components).filter(id => before.components[id].group === group);
          if (!members.length) throw Error('Required component group unavailable');
          return members;
        });
        const pairs = await Promise.all([...new Set([...ids, ...grouped])].map(async id => {
          const component = before.components[id];
          if (!component || !component.path.endsWith('.json')) throw Error('Required component unavailable');
          const url = new URL(component.path, root); url.searchParams.set('v', component.sha256);
          // URLs carry the content hash, so the HTTP cache is safe; a retry reloads in case a deploy cached stale bytes.
          const bytes = await request(url.href, {cache: attempt ? 'reload' : 'default'}, async response => {
            if (!response.ok) throw Error('Data component unavailable');
            return response.arrayBuffer();
          }, component.bytes);
          const digest = hex(await cryptoAPI.subtle.digest('SHA-256', bytes));
          if (bytes.byteLength !== component.bytes || digest !== component.sha256) throw Error('Data snapshot mismatch');
          const value = JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(bytes));
          validateData(id, value);
          return [id, value];
        }));
        const after = await manifest();
        if (after.snapshot_sha256 !== before.snapshot_sha256) throw Error('Data snapshot changed during loading');
        const result = {snapshot:before.snapshot_sha256, manifest:before, data:Object.fromEntries(pairs),
          hashes:Object.fromEntries(pairs.map(([id]) => [id, before.components[id].sha256])), recovered:attempt > 0};
        notify('validated');
        return result;
      } catch (reason) { error = reason; }
    }
    notify('failed');
    throw error;
  }
  // One record from the static API, bound to a validated list row by the SHA-256 prefix that row carries.
  async function record(path, digest, options = {}) {
    if (!/^[a-f0-9]{16,64}$/.test(digest || '')) throw Error('Invalid record digest');
    const cryptoAPI = options.crypto || globalThis.crypto;
    const url = new URL(path, new URL(options.root || defaultRoot)); url.searchParams.set('v', digest);
    const response = await (options.fetch || globalThis.fetch)(url.href);
    if (!response.ok) throw Error('Record unavailable');
    const bytes = await response.arrayBuffer();
    if (!hex(await cryptoAPI.subtle.digest('SHA-256', bytes)).startsWith(digest)) throw Error('Record snapshot mismatch');
    return JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(bytes));
  }
  function observe(target, loaded) {
    target.dataset.snapshotSha256 = loaded.snapshot;
    target.dataset.componentSha256 = JSON.stringify(loaded.hashes);
    target.dataset.loadState = 'ready';
  }
  function panel() {
    let node = document.getElementById('data-snapshot-status');
    if (!node) {
      node = document.createElement('div'); node.id = 'data-snapshot-status'; node.className = 'wrap snapshot-status';
      node.setAttribute('role', 'status'); node.setAttribute('aria-live', 'polite');
      document.querySelector('main').before(node);
    }
    return node;
  }
  function run(ids, render, options = {}) {
    const disabledBeforeLoad = new WeakMap();
    const currentControls = () => [...document.querySelectorAll(options.controls || 'main select, main button, main input')];
    const disableControls = () => currentControls().forEach(node => {
      if (!disabledBeforeLoad.has(node)) disabledBeforeLoad.set(node, node.disabled);
      node.disabled = true;
    });
    const restoreControls = () => currentControls().forEach(node => {
      if (disabledBeforeLoad.has(node)) node.disabled = disabledBeforeLoad.get(node);
    });
    const start = async () => {
      const target = document.documentElement, status = panel();
      target.dataset.loadState = 'loading'; delete target.dataset.snapshotSha256; delete target.dataset.componentSha256;
      disableControls();
      options.clear?.();
      status.textContent = tr('Loading a consistent data snapshot…');
      let loaded;
      try {
        loaded = await load(ids, {groups:options.groups});
        restoreControls();
        await render(loaded);
        observe(target, loaded);
        const oldPage = target.dataset.pageSnapshot && target.dataset.pageSnapshot !== loaded.snapshot;
        status.replaceChildren();
        const text = document.createElement('span');
        text.textContent = tr('Data snapshot {id}. ', {id: loaded.snapshot.slice(0, 12)}) + (oldPage ? tr('The validated data snapshot differs from this page’s generated snapshot. ') : loaded.recovered ? tr('A consistent snapshot loaded after retry. ') : '');
        const link = document.createElement('a'); link.href = new URL('api/v1/manifest.json', defaultRoot).href; link.textContent = tr('Component dates and hashes');
        status.append(text, link);
      } catch (error) {
        disableControls();
        target.dataset.loadState = 'failed';
        delete target.dataset.snapshotSha256; delete target.dataset.componentSha256;
        options.clear?.(); status.replaceChildren();
        const message = document.createElement('p');
        message.textContent = tr('A consistent data snapshot could not be loaded. ') + (error.message?.startsWith('Secure SHA-256') ? error.message + ' ' : '') + tr('Your query is preserved; retry or use the static pages and downloads.');
        const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = tr('Retry');
        retry.addEventListener('click', start);
        const links = document.createElement('p');
        for (const [label, path] of [[tr('Static discovery pages'), 'profiles/index.html'], [tr('Dataset downloads'), 'dataset.html'], [tr('Scientific JSON'), 'data/discoveries.json'], [tr('Security JSON'), 'data/vulnerabilities-overview.json']]) {
          const a = document.createElement('a'); a.href = new URL(path, defaultRoot).href; a.textContent = label; links.append(a, document.createTextNode(' · '));
        }
        status.append(message, retry, links);
      }
    };
    // A speculative prerender must not download megabytes of data the reader may never open.
    if (document.prerendering) return new Promise(done => document.addEventListener('prerenderingchange', () => done(start()), {once:true}));
    return start();
  }
  globalThis.CatalogData = {load, observe, record, run, validateManifest};
  if (typeof module !== 'undefined') module.exports = globalThis.CatalogData;
})();
