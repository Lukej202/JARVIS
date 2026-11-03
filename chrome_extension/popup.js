'use strict';
const $ = id => document.getElementById(id);
let latest = null;
let busy = false;

async function send(type, details = {}) {
  const response = await chrome.runtime.sendMessage({type, ...details});
  if (!response?.ok) throw new Error(response?.error || 'JARVIS extension did not respond.');
  return response.data;
}
function status(text, error = false) {
  $('status').textContent = text;
  $('status').classList.toggle('error', error);
}
async function run(action) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(button => {button.disabled = true;});
  try { await action(); }
  catch (error) { status(error.message, true); }
  finally {
    busy = false;
    document.querySelectorAll('button').forEach(button => {button.disabled = false;});
  }
}
function renderRead(result) {
  latest = result?.lastRead || null;
  $('page').hidden = !latest;
  if (!latest) return;
  $('title').textContent = latest.title || 'Untitled';
  $('url').textContent = latest.url || '';
  $('preview').textContent = latest.text?.slice(0, 4500) || '(No visible text extracted)';
  $('links').replaceChildren();
  const links = result.links || [];
  $('links-heading').hidden = !links.length;
  for (const link of links) {
    const button = document.createElement('button');
    button.textContent = link.label || link.url;
    button.title = link.url;
    button.addEventListener('click', () => run(async () => {
      await send('OPEN_LINK', {href: link.url});
      status('Opened a new JARVIS tab. Reopen this popup to read it.');
    }));
    $('links').append(button);
  }
}
$('search').addEventListener('click', () => run(async () => {
  const query = $('query').value.trim();
  await send('START_SEARCH', {query});
  status('Research tab opened in your regular Chrome window. Reopen this popup and click Read JARVIS Tab.');
}));
$('read').addEventListener('click', () => run(async () => {
  const state = await send('GET_STATE');
  if (!state.tabId) throw new Error('No JARVIS tab found. Open a search first.');
  const url = new URL(state.url);
  if (!['https:', 'http:'].includes(url.protocol)) throw new Error('Not a public website.');
  const originPattern = url.origin + '/*';
  let granted = await chrome.permissions.contains({origins: [originPattern]});
  if (!granted) {
    granted = await chrome.permissions.request({origins: [originPattern]});
    if (!granted) throw new Error('Website permission not granted.');
  }
  const result = await send('READ_LAST');
  renderRead(result);
  status('Read JARVIS tab successfully. Your other Chrome tabs were untouched.');
}));
$('close').addEventListener('click', () => run(async () => {
  const result = await send('CLOSE_TABS');
  renderRead(null);
  status('Closed ' + result.closed + ' JARVIS-created tab(s).');
}));
$('copy').addEventListener('click', () => run(async () => {
  if (!latest) return;
  await navigator.clipboard.writeText(`Title: ${latest.title}\nURL: ${latest.url}\n\n${latest.text}`);
  status('Page text copied to clipboard.');
}));
$('query').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {event.preventDefault(); $('search').click();}
});
send('GET_STATE').then(state => {
  if (state.tabId) status('Last JARVIS tab: ' + (state.title || state.url || 'Ready to read'));
}).catch(error => status(error.message, true));

$('pair').addEventListener('click', () => run(async () => {
  const key = $('bridge-key').value.trim();
  await send('SET_BRIDGE_KEY', {key});
  $('bridge-key').value = '';
  $('bridge-status').textContent = 'Bridge: connected to local JARVIS';
  status('Paired. Approved research tasks can now open new tabs automatically.');
}));
send('BRIDGE_STATUS').then(info => {
  $('bridge-status').textContent = info.connected ? 'Bridge: connected to local JARVIS' : 'Bridge: ' + (info.note || 'not connected');
}).catch(() => { $('bridge-status').textContent = 'Bridge: unavailable'; });
