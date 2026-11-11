'use strict';

// JARVIS research-tab manager for the user's existing Chrome profile.
// IMPORTANT: This extension has broad website host permissions but every DOM
// operation checks the tab ID against the list of tabs created by THIS extension.
// It does not read pre-existing tabs or send cookies/browser history to Flask.
const STORAGE_KEY = 'jarvisResearch';
const PAIRING_KEY = 'jarvisLocalPairingKey';
const BASE = 'http://127.0.0.1:5000';
const MAX_TABS = 18;
const MAX_LINKS = 20;
let polling = false;

function isPublicWebUrl(raw) {
  try {
    const u = new URL(raw);
    if (u.protocol !== 'https:' || u.username || u.password || u.port) return false;
    const h = u.hostname.toLowerCase().replace(/\.$/, '');
    if (!h.includes('.') || h.includes(':') || h === 'localhost') return false;
    if (/\.(local|localhost|internal|lan|test)$/i.test(h)) return false;
    if (['0.0.0.0', '169.254.169.254'].includes(h)) return false;
    if (h.startsWith('127.') || h.startsWith('10.') || h.startsWith('192.168.')) return false;
    const v4 = h.split('.');
    if (v4.length === 4 && v4.every(v => /^\d+$/.test(v))) {
      const a = v4.map(Number);
      if (a.some(v => v > 255) || a[0] === 0 || a[0] === 172 && a[1] >= 16 && a[1] <= 31 || a[0] === 169 && a[1] === 254 || a[0] === 100 && a[1] >= 64 && a[1] <= 127) return false;
    }
    // JARVIS is allowed public research, never accounts/messages/payments.
    const denied = ['accounts.google.com','myaccount.google.com','mail.google.com',
      'drive.google.com','docs.google.com','chatgpt.com','chat.openai.com',
      'outlook.live.com','outlook.office.com','login.microsoftonline.com',
      'paypal.com','www.paypal.com','stripe.com','dashboard.stripe.com',
      'github.com/login','bankofamerica.com','chase.com'];
    if (denied.some(s => h === s || (s.indexOf('/') === -1 && h.endsWith('.' + s)))) return false;
    if (/(?:^|\/)(?:login|signin|sign-in|account|checkout|cart|billing|settings)(?:\/|$)/i.test(u.pathname)) return false;
    return true;
  } catch (_) { return false; }
}

async function readState() {
  const data = await chrome.storage.session.get(STORAGE_KEY);
  return data[STORAGE_KEY] || {owned: [], lastId: null, lastRead: null, links: []};
}
async function writeState(state) { await chrome.storage.session.set({[STORAGE_KEY]: state}); }
async function addOwned(tab) {
  const state = await readState();
  state.owned = [...state.owned.filter(id => id !== tab.id), tab.id].slice(-MAX_TABS);
  state.lastId = tab.id;
  state.lastRead = null;
  state.links = [];
  await writeState(state);
}
async function ownedTab(tabId) {
  const state = await readState();
  if (!state.owned.includes(tabId)) throw new Error('Attempt to access a non-JARVIS tab blocked.');
  const tab = await chrome.tabs.get(tabId);
  if (!isPublicWebUrl(tab.url || '')) throw new Error('The JARVIS tab is not on an approved public HTTPS page.');
  return tab;
}
async function getLastOwned() {
  const state = await readState();
  if (!state.lastId) throw new Error('No JARVIS tab has been opened.');
  const tab = await ownedTab(state.lastId);
  return {state, tab};
}
function collectPage() {
  const title = (document.title || '').slice(0, 240);
  const text = (document.querySelector('main, article, [role="main"]')?.innerText || document.body?.innerText || '')
    .replace(/\n{4,}/g, '\n\n\n').slice(0, 14000);
  const links = [];
  const seen = new Set();
  // Only fixed, read-only DOM extraction code runs inside the page.
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href;
    if (!href.startsWith('https://') || seen.has(href)) continue;
    const label = (a.innerText || a.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 100);
    if (!label) continue;
    seen.add(href);
    links.push({label, url: href});
    if (links.length >= 60) break;
  }
  return {title, url: location.href, text, links};
}

function collectSearchResults() {
  const results = [];
  const seen = new Set();
  let links = [];
  if (location.hostname.includes('bing.com')) {
    links = [...document.querySelectorAll('li.b_algo h2 a[href], h2 a[href]')];
  } else {
    links = [...document.querySelectorAll('a:has(h3)')];
  }
  for (const a of links) {
    try {
      const url = new URL(a.href);
      if (url.protocol !== 'https:' || url.hostname.endsWith('google.com') ||
          url.hostname.endsWith('bing.com') || seen.has(url.href)) continue;
      const title = (a.innerText || a.querySelector('h3')?.innerText || '').trim().slice(0, 160);
      if (!title || title.length < 5) continue;
      seen.add(url.href);
      const snippet = (a.closest('li.b_algo, .MjjYud, .g')?.innerText || a.parentElement?.parentElement?.innerText || '')
        .trim().replace(/\s+/g, ' ').slice(0, 360);
      results.push({title, url: url.href, snippet});
      if (results.length >= 12) break;
    } catch (_) { /* skip invalid result link */ }
  }
  return {title: document.title, results};
}

function extractResearchText() {
  if (document.querySelector('input[type="password"],form[action*="/login"],form[action*="/signin"]')) {
    return {blocked: true, reason: 'Login or password form detected; page was not read.'};
  }
  const title = (document.title || '').slice(0, 220);
  const body = document.querySelector('article, main, [role="main"]') || document.body;
  const text = String(body?.innerText || '').replace(/\n{4,}/g, '\n\n\n').slice(0, 6800);
  if (/just a moment|verify you are human|checking your browser/i.test(title) ||
      (/enable javascript.*cookies|checking your browser/i.test(text) && text.length < 900)) {
    return {blocked:true,reason:'Bot-check or verification page.'};
  }
  return {title, url: location.href, text};
}

async function createResearchTab(url, windowId, taskTabIds = null) {
  if (!isPublicWebUrl(url)) throw new Error('Rejected non-public or sensitive research URL: ' + url.slice(0, 100));
  const options = {url, active:true};
  if (windowId) options.windowId = windowId;
  const tab = await chrome.tabs.create(options);
  // Record task ownership immediately, even if later registration fails.
  if (taskTabIds) taskTabIds.add(tab.id);
  await addOwned(tab);
  return tab;
}
async function waitReady(id, timeoutMs = 16000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const tab = await chrome.tabs.get(id);
      if (tab.status === 'complete') {
        await new Promise(resolve => setTimeout(resolve, 900));
        return;
      }
    } catch (error) { throw new Error('JARVIS research tab was closed.'); }
    await new Promise(resolve => setTimeout(resolve, 350));
  }
  throw new Error('Page navigation timed out.');
}
async function injectOwned(tabId, func) {
  await ownedTab(tabId); // Guard before each DOM read.
  const injected = await chrome.scripting.executeScript({target:{tabId}, func});
  const result = injected?.[0]?.result;
  if (!result) throw new Error('No readable page content.');
  const current = await ownedTab(tabId); // Guard after, in case the tab navigated.
  if (result.url && new URL(result.url).origin !== new URL(current.url).origin) {
    throw new Error('Tab navigated while reading; content discarded.');
  }
  return result;
}

chrome.tabs.onRemoved.addListener(async tabId => {
  try {
    const state = await readState();
    if (!state.owned.includes(tabId)) return;
    state.owned = state.owned.filter(id => id !== tabId);
    if (state.lastId === tabId) {
      state.lastId = state.owned.at(-1) || null;
      state.lastRead = null;
      state.links = [];
    }
    await writeState(state);
  } catch (_) {}
});

async function bridgeFetch(path, options = {}) {
  const state = await chrome.storage.local.get(PAIRING_KEY);
  const key = state[PAIRING_KEY];
  if (!key) throw new Error('JARVIS extension is not paired yet.');
  const response = await fetch(BASE + path, {
    ...options,
    cache:'no-store',
    headers: {'X-JARVIS-Extension-Key': key, ...(options.headers || {})},
  });
  if (!response.ok) throw new Error(`Local JARVIS server returned HTTP ${response.status}.`);
  return await response.json();
}
async function cancelled(jobId) {
  try { return (await bridgeFetch('/extension/cancel/' + encodeURIComponent(jobId))).cancelled; }
  catch (_) { return true; } // Fail closed when the local server disappears.
}

// Close ONLY the tabs created by the approved automatic research task.
// The extension's manually opened research tabs and the user's own tabs remain.
async function closeTaskResearchTabs(taskTabIds) {
  if (!taskTabIds.size) return;
  let toClose;
  try {
    const state = await readState();
    toClose = [...taskTabIds].filter(id => state.owned.includes(id));
    // Forget the tabs before closing them so onRemoved cannot race with state updates.
    state.owned = state.owned.filter(id => !taskTabIds.has(id));
    if (taskTabIds.has(state.lastId)) {
      state.lastId = state.owned.at(-1) || null;
      state.lastRead = null;
      state.links = [];
    }
    await writeState(state);
  } catch (error) {
    // Fail safe: if we cannot verify ownership, do not risk closing user tabs.
    console.warn('JARVIS: could not verify tab ownership for cleanup.', error);
    return;
  }
  for (const tabId of toClose) {
    try { await chrome.tabs.remove(tabId); }
    catch (_) { /* User may have already closed the research tab. */ }
  }
}

async function conductResearch(job) {
  const taskTabIds = new Set();
  try {
    const query = String(job.query || '').slice(0, 220);
    const pages = Math.min(Math.max(Number(job.pages) || 1, 1), 3);
    const report = {query, pages:[], errors:[], stopped:false};
    const win = await chrome.windows.getLastFocused({windowTypes:['normal']}).catch(() => null);
    const windowId = win?.type === 'normal' ? win.id : undefined;
    if (await cancelled(job.id)) { report.stopped = true; return report; }
    const search = await createResearchTab('https://www.google.com/search?q=' + encodeURIComponent(query), windowId, taskTabIds);
    let hits = [];
    for (const engine of ['google', 'bing']) {
      try {
        if (engine === 'bing') await chrome.tabs.update(search.id, {url:'https://www.bing.com/search?q=' + encodeURIComponent(query)});
        await waitReady(search.id);
        const result = await injectOwned(search.id, collectSearchResults);
        hits = (result.results || []).filter(item => isPublicWebUrl(item.url));
        if (hits.length) break;
        report.errors.push(engine + ': no normal search results extracted (possibly a consent page).');
      } catch (error) { report.errors.push(engine + ': ' + String(error.message).slice(0, 170)); }
    }
    for (const hit of hits) {
      if (report.pages.length >= pages) break;
      if (await cancelled(job.id)) { report.stopped = true; break; }
      try {
        const tab = await createResearchTab(hit.url, search.windowId, taskTabIds);
        await waitReady(tab.id);
        const page = await injectOwned(tab.id, extractResearchText);
        if (page.blocked) { report.errors.push(hit.url + ': ' + page.reason); continue; }
        if (!isPublicWebUrl(page.url)) { report.errors.push(hit.url + ': redirected to excluded URL'); continue; }
        if (String(page.text || '').trim().length < 160) { report.errors.push(hit.url + ': not enough visible text'); continue; }
        report.pages.push({title:page.title || hit.title, url:page.url, preview:page.text.slice(0, 6500)});
      } catch (error) {
        report.errors.push(hit.url.slice(0, 120) + ': ' + String(error.message).slice(0, 130));
      }
    }
    if (await cancelled(job.id)) report.stopped = true;
    return report;
  } finally {
    // Runs on success, failure, and STOP BROWSING.
    await closeTaskResearchTabs(taskTabIds);
  }
}
async function pollBridge() {
  if (polling) return;
  polling = true;
  try {
    const config = await chrome.storage.local.get(PAIRING_KEY);
    if (!config[PAIRING_KEY]) return;
    const answer = await bridgeFetch('/extension/next');
    if (!answer.job) return;
    const job = answer.job;
    let payload;
    try { payload = {id:job.id, report:await conductResearch(job)}; }
    catch (error) { payload = {id:job.id, error:String(error?.message || error)}; }
    try {
      await bridgeFetch('/extension/result', {method:'POST',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    } catch (error) { console.error('JARVIS result delivery failed:', error); }
  } catch (_) {
    // Flask may be offline. Alarms will retry without touching any Chrome tabs.
  } finally { polling = false; }
}

chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === 'jarvisBridgePoll') pollBridge(); });
chrome.runtime.onStartup.addListener(() => { chrome.alarms.create('jarvisBridgePoll', {periodInMinutes:0.5}); pollBridge(); });
chrome.runtime.onInstalled.addListener(() => { chrome.alarms.create('jarvisBridgePoll', {periodInMinutes:0.5}); pollBridge(); });
chrome.alarms.create('jarvisBridgePoll', {periodInMinutes:0.5});
setInterval(pollBridge, 3000); // Faster while service worker is active; alarm wakes it if suspended.
pollBridge();

async function dispatch(message) {
  switch (message.type) {
    case 'SET_BRIDGE_KEY': {
      const key = String(message.key || '').trim();
      if (key.length < 30 || key.length > 200) throw new Error('Invalid pairing key.');
      await chrome.storage.local.set({[PAIRING_KEY]:key});
      try {
        await bridgeFetch('/extension/health');
      } catch (error) {
        await chrome.storage.local.remove(PAIRING_KEY);
        throw new Error('Could not pair: check key and ensure Flask is running on port 5000.');
      }
      pollBridge();
      return {connected:true};
    }
    case 'BRIDGE_STATUS': {
      const config = await chrome.storage.local.get(PAIRING_KEY);
      if (!config[PAIRING_KEY]) return {connected:false, note:'Not paired'};
      try { await bridgeFetch('/extension/health'); return {connected:true}; }
      catch (_) { return {connected:false, note:'Flask offline or pairing key invalid'}; }
    }
    case 'START_SEARCH': {
      const query = String(message.query || '').trim().slice(0, 250);
      if (!query) throw new Error('Enter a research topic.');
      const tab = await createResearchTab('https://www.google.com/search?q=' + encodeURIComponent(query));
      return {opened:true,tabId:tab.id};
    }
    case 'GET_STATE': {
      const state = await readState();
      let tab = null;
      if (state.lastId) { try { tab = await ownedTab(state.lastId); } catch (_) {} }
      return {tabId:tab?.id || null, url:tab?.url || '', title:tab?.title || '', lastRead:state.lastRead, links:state.links};
    }
    case 'READ_LAST': {
      const {state,tab} = await getLastOwned();
      const permitted = await chrome.permissions.contains({origins:[new URL(tab.url).origin + '/*']});
      if (!permitted) throw new Error('Website access permission is required.');
      // Google search navigation/account links are excluded from the page read.
      let result;
      if (new URL(tab.url).hostname === 'www.google.com' && new URL(tab.url).pathname === '/search') {
        const search = await injectOwned(tab.id, collectSearchResults);
        result = {title:search.title, url:tab.url,
          text:(search.results || []).map(item => item.title + '\n' + item.snippet).join('\n\n'),
          links:(search.results || []).map(item => ({label:item.title,url:item.url}))};
      } else result = await injectOwned(tab.id, collectPage);
      state.lastRead = {title:result.title,url:result.url,text:String(result.text || '').slice(0, 14000)};
      state.links = (result.links || []).filter(item => isPublicWebUrl(item.url)).slice(0, MAX_LINKS);
      await writeState(state);
      return {lastRead:state.lastRead,links:state.links};
    }
    case 'OPEN_LINK': {
      const state = await readState();
      const href = String(message.href || '');
      if (!state.lastId || !state.owned.includes(state.lastId) ||
          !state.links.some(item => item.url === href) || !isPublicWebUrl(href)) {
        throw new Error('Link was not collected from a JARVIS-created tab.');
      }
      const previous = await ownedTab(state.lastId);
      const tab = await createResearchTab(href, previous.windowId);
      return {opened:true,tabId:tab.id};
    }
    case 'CLOSE_TABS': {
      const state = await readState();
      await writeState({owned:[],lastId:null,lastRead:null,links:[]});
      for (const id of state.owned) { try { await chrome.tabs.remove(id); } catch (_) {} }
      return {closed:state.owned.length};
    }
    default: throw new Error('Unknown JARVIS extension message.');
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || !sender.url?.startsWith(chrome.runtime.getURL('popup.html'))) {
    sendResponse({ok:false,error:'Unauthorized extension message.'});
    return false;
  }
  dispatch(message).then(data => sendResponse({ok:true,data}))
    .catch(error => sendResponse({ok:false,error:String(error?.message || error)}));
  return true;
});
