'use strict';
(() => {
  const TOKEN = document.querySelector('meta[name="jarvis-token"]').content;
  const $ = (id) => document.getElementById(id);
  const startButton = $('start');
  const stopButton = $('stop');
  const sendButton = $('send');
  const input = $('typed');
  const messageList = $('messages');
  const speechButton = $('speech-toggle');
  let recorder = null;
  let stream = null;
  let pieces = [];
  let audioUrl = null;
  let busy = false;
  let recording = false;
  let speechEnabled = true;
  let toastTimer = null;

  function setMode(mode, label, description) {
    document.body.dataset.mode = mode;
    $('core-mode').textContent = label;
    $('status-text').textContent = description;
  }
  function showToast(text, error = false) {
    const toast = $('toast');
    toast.textContent = text;
    toast.classList.toggle('error', error);
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 6500);
  }
  async function api(path, {method = 'GET', json = null, form = null} = {}) {
    const options = {method, headers: {'X-JARVIS-Token': TOKEN}, cache: 'no-store'};
    if (json !== null) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(json);
    } else if (form !== null) {
      options.body = form;
    }
    const response = await fetch(path, options);
    let data;
    try { data = await response.json(); }
    catch { throw new Error('The local server did not return a valid response.'); }
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
    return data;
  }
  function speak(text) {
    if (!speechEnabled || !('speechSynthesis' in window)) {
      setMode('idle', 'SYSTEM READY', 'Ready for your next command.');
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text.replace(/\*\*/g, '').replace(/[`#]/g, ''));
    utterance.rate = 1.0;
    utterance.pitch = 0.9;
    utterance.onstart = () => setMode('speaking', 'SPEAKING', 'Playing JARVIS voice response.');
    utterance.onend = () => setMode('idle', 'SYSTEM READY', 'Ready for your next command.');
    utterance.onerror = () => setMode('idle', 'SYSTEM READY', 'Ready for your next command.');
    window.speechSynthesis.speak(utterance);
  }
  // Render a minimal subset of Markdown without converting model text to HTML.
  function renderInline(text, target) {
    const pattern = /(\*\*(.+?)\*\*|`([^`]+)`)/gs;
    let last = 0;
    for (const match of text.matchAll(pattern)) {
      target.append(document.createTextNode(text.slice(last, match.index)));
      const node = document.createElement(match[2] === undefined ? 'code' : 'strong');
      node.textContent = match[2] === undefined ? match[3] : match[2];
      target.append(node);
      last = match.index + match[0].length;
    }
    target.append(document.createTextNode(text.slice(last)));
  }
  function addMessage(role, text) {
    const empty = messageList.querySelector('.empty-conversation');
    if (empty) empty.remove();
    const message = document.createElement('article');
    message.className = `message ${role === 'user' ? 'user' : 'assistant'}`;
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'user' ? 'YOU' : 'J';
    const body = document.createElement('div');
    body.className = 'message-body';
    const name = document.createElement('div');
    name.className = 'message-name';
    name.textContent = role === 'user' ? 'YOU / INPUT' : 'JARVIS / RESPONSE';
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    renderInline(text, bubble);
    body.append(name, bubble);
    message.append(avatar, body);
    messageList.append(message);
    messageList.scrollTop = messageList.scrollHeight;
  }
  function showEmptyConversation() {
    messageList.replaceChildren();
    const empty = document.createElement('div');
    empty.className = 'empty-conversation';
    const glyph = document.createElement('div');
    glyph.className = 'empty-glyph';
    glyph.textContent = '>_';
    const title = document.createElement('strong');
    title.textContent = 'Your conversation starts here';
    const explanation = document.createElement('p');
    explanation.textContent = 'Ask a question, give a command, or use your microphone. Terminal and voice share the same memory.';
    empty.append(glyph, title, explanation);
    messageList.append(empty);
  }
  async function refreshHistory() {
    const data = await api('/history');
    const messages = Array.isArray(data.messages) ? data.messages : [];
    const fingerprint = JSON.stringify(messages);
    if (fingerprint === refreshHistory.lastFingerprint) return;
    const nearBottom = messageList.scrollHeight - messageList.clientHeight - messageList.scrollTop < 150;
    refreshHistory.lastFingerprint = fingerprint;
    messageList.replaceChildren();
    if (!messages.length) showEmptyConversation();
    else for (const m of messages) addMessage(m.role, m.text);
    $('conversation-count').textContent = `${messages.length} MESSAGE${messages.length === 1 ? '' : 'S'}`;
    if (!nearBottom && messages.length) messageList.scrollTop = 0;
  }
  function setBusy(value) {
    busy = value;
    sendButton.disabled = value;
    input.disabled = value;
    startButton.disabled = value || recording;
  }
  async function sendCommand(text) {
    text = String(text || '').trim();
    if (!text || busy) return;
    setBusy(true);
    addMessage('user', text);
    setMode('thinking', 'PROCESSING', 'Qwen3 is interpreting your request...');
    try {
      const result = await api('/command', {method: 'POST', json: {text}});
      addMessage('assistant', result.reply);
      await Promise.allSettled([refreshPending(), refreshActivity()]);
      await refreshHistory().catch(() => {});
      speak(result.reply);
    } catch (error) {
      setMode('error', 'COMMAND FAILED', error.message);
      showToast(error.message, true);
      addMessage('assistant', 'Command failed: ' + error.message);
    } finally {
      setBusy(false);
    }
  }
  sendButton.addEventListener('click', () => {
    const text = input.value;
    if (!text.trim()) return;
    input.value = '';
    sendCommand(text);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      sendButton.click();
    }
  });
  speechButton.addEventListener('click', () => {
    speechEnabled = !speechEnabled;
    speechButton.setAttribute('aria-pressed', String(speechEnabled));
    speechButton.setAttribute('aria-label', speechEnabled ? 'Turn voice replies off' : 'Turn voice replies on');
    speechButton.title = speechEnabled ? 'Voice replies on' : 'Voice replies off';
    speechButton.querySelector('use').setAttribute('href', speechEnabled ? '#i-volume' : '#i-volume-off');
    if (!speechEnabled) {
      window.speechSynthesis?.cancel();
      if (!busy && !recording) setMode('idle', 'SYSTEM READY', 'Voice replies muted.');
    }
  });
  startButton.addEventListener('click', async () => {
    if (busy || recording) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      showToast('Microphone recording is not supported by this browser.', true);
      return;
    }
    startButton.disabled = true;
    try {
      window.speechSynthesis?.cancel();
      stream = await navigator.mediaDevices.getUserMedia({audio: true});
      pieces = [];
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (event) => { if (event.data.size) pieces.push(event.data); };
      recorder.onerror = () => {
        setMode('error', 'RECORDING ERROR', 'The microphone recorder encountered an error.');
        showToast('Recording failed.', true);
        cleanupAudio();
      };
      recorder.onstop = processAudio;
      recorder.start();
      recording = true;
      stopButton.disabled = false;
      $('mic-label').textContent = 'MICROPHONE ACTIVE';
      setMode('listening', 'LISTENING', 'Speak naturally, then press Stop.');
    } catch (error) {
      setMode('error', 'MIC ERROR', error.message);
      showToast('Microphone error: ' + error.message, true);
      cleanupAudio();
    }
  });
  stopButton.addEventListener('click', () => {
    if (recorder?.state === 'recording') {
      stopButton.disabled = true;
      setMode('thinking', 'PROCESSING AUDIO', 'Finishing microphone recording...');
      recorder.stop();
    }
  });
  function cleanupAudio() {
    if (stream) { for (const track of stream.getTracks()) track.stop(); stream = null; }
    recording = false;
    stopButton.disabled = true;
    startButton.disabled = busy;
    $('mic-label').textContent = 'MICROPHONE INACTIVE';
  }
  async function processAudio() {
    cleanupAudio();
    const audio = new Blob(pieces, {type: recorder?.mimeType || 'audio/webm'});
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = URL.createObjectURL(audio);
    $('playback').src = audioUrl;
    if (!audio.size) {
      setMode('error', 'NO AUDIO', 'The recording was empty. Please try again.');
      return;
    }
    setBusy(true);
    setMode('thinking', 'TRANSCRIBING', 'Whisper is converting audio to text locally...');
    try {
      const form = new FormData();
      const extension = audio.type.includes('mp4') ? 'mp4' : 'webm';
      form.append('audio', audio, `recording.${extension}`);
      const result = await api('/transcribe', {method: 'POST', form});
      if (!result.text) {
        setMode('idle', 'SYSTEM READY', 'Whisper did not detect speech. Try again.');
        return;
      }
      showToast('Heard: ' + result.text);
      setBusy(false);
      await sendCommand(result.text);
    } catch (error) {
      setMode('error', 'TRANSCRIPTION FAILED', error.message);
      showToast(error.message, true);
    } finally {
      setBusy(false);
    }
  }
  function makeIcon(id) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'icon');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', '#' + id);
    svg.append(use);
    return svg;
  }
  async function refreshPending() {
    const data = await api('/pending');
    const list = Array.isArray(data.actions) ? data.actions : [];
    $('approval-count').textContent = String(list.length);
    $('nav-approval-count').textContent = String(list.length);
    const target = $('actions');
    target.replaceChildren();
    if (!list.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-action';
      const circle = document.createElement('div');
      circle.className = 'empty-check';
      circle.append(makeIcon('i-check'));
      const strong = document.createElement('strong');
      strong.textContent = 'No actions awaiting approval';
      const desc = document.createElement('span');
      desc.textContent = 'Protected operations will appear here.';
      empty.append(circle, strong, desc);
      target.append(empty);
      return;
    }
    for (const item of list) {
      const card = document.createElement('article');
      card.className = 'action-card';
      const kind = document.createElement('div');
      kind.className = 'action-kind';
      kind.textContent = (item.kind || 'ACTION').replaceAll('_', ' ');
      const heading = document.createElement('h3');
      heading.textContent = item.summary;
      const id = document.createElement('div');
      id.className = 'action-id';
      id.textContent = 'ID: ' + item.id;
      card.append(kind, heading, id);
      if (item.content) {
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = 'Review proposed content';
        const preview = document.createElement('pre');
        preview.textContent = item.content;
        details.append(summary, preview);
        card.append(details);
      }
      const controls = document.createElement('div');
      controls.className = 'action-buttons';
      const yes = document.createElement('button');
      yes.textContent = 'Approve action';
      const no = document.createElement('button');
      no.textContent = 'Deny';
      no.className = 'deny';
      for (const [button, approved] of [[yes, true], [no, false]]) {
        button.addEventListener('click', async () => {
          yes.disabled = true; no.disabled = true;
          try {
            const outcome = await api('/action', {method: 'POST', json: {id: item.id, approved}});
            showToast(outcome.reply);
            await Promise.allSettled([refreshPending(), refreshActivity(), refreshHistory()]);
          } catch (error) {
            showToast(error.message, true);
            yes.disabled = false; no.disabled = false;
          }
        });
      }
      controls.append(yes, no);
      card.append(controls);
      target.append(card);
    }
  }
  async function refreshActivity() {
    const data = await api('/activity');
    const actions = Array.isArray(data.actions) ? data.actions : [];
    const target = $('activity-list');
    target.replaceChildren();
    if (!actions.length) {
      const empty = document.createElement('div');
      empty.className = 'activity-empty';
      empty.textContent = 'No recorded operations yet.';
      target.append(empty);
      return;
    }
    for (const item of actions) {
      const row = document.createElement('div'); row.className = 'activity-item';
      const symbol = document.createElement('div'); symbol.className = 'activity-symbol';
      symbol.append(makeIcon('i-activity'));
      const body = document.createElement('div'); body.className = 'activity-text';
      const title = document.createElement('strong'); title.textContent = item.summary;
      const time = document.createElement('small');
      time.textContent = new Date(item.created_at * 1000).toLocaleString();
      body.append(title, time);
      const status = document.createElement('span');
      status.className = 'activity-badge ' + item.status;
      status.textContent = item.status.toUpperCase();
      row.append(symbol, body, status);
      if (item.result) row.title = item.result;
      target.append(row);
    }
  }
  function setDiagnostic(key, state, label) {
    const led = $('led-' + key);
    led.className = 'led ' + (state === 'ready' ? 'ok' : (state === 'offline' ? 'fail' : 'warn'));
    $('diag-' + key).textContent = label;
  }
  async function refreshStatus() {
    try {
      const status = await api('/status');
      setDiagnostic('ollama', status.ollama, status.ollama === 'ready' ? 'Online' : status.ollama === 'model_missing' ? 'No model' : 'Offline');
      setDiagnostic('whisper', status.whisper, status.whisper === 'ready' ? 'Ready' : 'Standby');
      setDiagnostic('windows', status.windows, status.windows === 'ready' ? 'Available' : 'Unverified');
      setDiagnostic('vision', status.vision, status.vision === 'ready' ? 'Installed' : 'Optional');
      $('model-label').textContent = (status.model || 'QWEN3:4B').toUpperCase();
      $('runtime-label').textContent = status.ollama === 'ready' ? 'LOCAL CORE ONLINE' : 'CORE UNAVAILABLE';
      $('runtime-chip').querySelector('.led').className = 'led ' + (status.ollama === 'ready' ? 'ok' : 'fail');
    } catch (error) {
      setDiagnostic('ollama', 'offline', 'Unavailable');
      $('runtime-label').textContent = 'SERVER OFFLINE';
      $('runtime-chip').querySelector('.led').className = 'led fail';
    }
  }
  function refreshAll() {
    refreshStatus();
    refreshHistory().catch(error => showToast('History: ' + error.message, true));
    refreshPending().catch(error => showToast('Approvals: ' + error.message, true));
    refreshActivity().catch(error => showToast('Activity: ' + error.message, true));
  }
  $('refresh-chat').addEventListener('click', () => refreshHistory().catch(error => showToast(error.message, true)));
  $('refresh-approvals').addEventListener('click', () => refreshPending().catch(error => showToast(error.message, true)));
  $('refresh-activity').addEventListener('click', () => refreshActivity().catch(error => showToast(error.message, true)));
  document.querySelectorAll('.nav-link').forEach(link => link.addEventListener('click', () => {
    document.querySelectorAll('.nav-link').forEach(n => n.classList.remove('selected'));
    link.classList.add('selected');
  }));
  refreshAll();
  setInterval(() => { if (!busy) refreshHistory().catch(() => {}); }, 14000);
  setInterval(() => { refreshPending().catch(() => {}); refreshActivity().catch(() => {}); }, 12000);
  setInterval(() => refreshStatus().catch(() => {}), 25000);
  window.addEventListener('beforeunload', () => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    if (stream) stream.getTracks().forEach(t => t.stop());
    window.speechSynthesis?.cancel();
  });
})();
