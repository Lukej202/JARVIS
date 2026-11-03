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
  let voiceSequence = 0;
  let voiceController = null;
  let voiceAudio = null;
  let voiceAudioUrl = null;

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
  // Cancel both local Kokoro audio and the browser TTS fallback.
  function stopSpeech() {
    voiceSequence += 1;
    if (voiceController) { voiceController.abort(); voiceController = null; }
    if (voiceAudio) {
      voiceAudio.pause();
      voiceAudio.removeAttribute('src');
      voiceAudio = null;
    }
    if (voiceAudioUrl) { URL.revokeObjectURL(voiceAudioUrl); voiceAudioUrl = null; }
    window.speechSynthesis?.cancel();
  }

  function speakWithBrowser(text, sequence) {
    if (!speechEnabled || sequence !== voiceSequence) return;
    if (!('speechSynthesis' in window)) {
      setMode('idle', 'SYSTEM READY', 'Voice playback unavailable.');
      return;
    }
    const clean = text.replace(/```[\s\S]*?```/g, 'Code block omitted.')
      .replace(/\*\*/g, '').replace(/[`#]/g, '').slice(0, 1200);
    const utterance = new SpeechSynthesisUtterance(clean);
    utterance.rate = 1.0;
    utterance.pitch = 0.9;
    utterance.onstart = () => {
      if (sequence === voiceSequence) setMode('speaking', 'SPEAKING', 'Browser voice fallback active.');
    };
    utterance.onend = utterance.onerror = () => {
      if (sequence === voiceSequence) setMode('idle', 'SYSTEM READY', 'Ready for your next command.');
    };
    window.speechSynthesis.speak(utterance);
  }

  async function speak(text) {
    stopSpeech();
    const sequence = voiceSequence;
    if (!speechEnabled) {
      setMode('idle', 'SYSTEM READY', 'Voice replies muted.');
      return;
    }
    const controller = new AbortController();
    voiceController = controller;
    setMode('thinking', 'GENERATING VOICE', 'Kokoro is generating bm_lewis speech locally...');
    try {
      const response = await fetch('/tts', {
        method: 'POST', cache: 'no-store', signal: controller.signal,
        headers: {'X-JARVIS-Token': TOKEN, 'Content-Type': 'application/json'},
        body: JSON.stringify({text})
      });
      if (!response.ok) throw new Error(`Kokoro returned HTTP ${response.status}`);
      const wav = await response.blob();
      if (!wav.size || sequence !== voiceSequence || !speechEnabled) return;
      voiceController = null;
      voiceAudioUrl = URL.createObjectURL(wav);
      const player = new Audio(voiceAudioUrl);
      voiceAudio = player;
      player.onplaying = () => {
        if (sequence === voiceSequence) setMode('speaking', 'SPEAKING', 'Playing Kokoro bm_lewis voice.');
      };
      player.onended = () => {
        if (sequence === voiceSequence) {
          stopSpeech();
          setMode('idle', 'SYSTEM READY', 'Ready for your next command.');
        }
      };
      player.onerror = () => {
        if (sequence === voiceSequence) {
          stopSpeech();
          speakWithBrowser(text, voiceSequence);
        }
      };
      await player.play();
    } catch (error) {
      if (error.name === 'AbortError' || sequence !== voiceSequence || !speechEnabled) return;
      if (voiceAudio) {
        voiceAudio.pause(); voiceAudio = null;
      }
      if (voiceAudioUrl) { URL.revokeObjectURL(voiceAudioUrl); voiceAudioUrl = null; }
      voiceController = null;
      showToast('Kokoro is unavailable. Using browser voice as fallback.', true);
      speakWithBrowser(text, sequence);
    }
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
    stopSpeech();
    setBusy(true);
    addMessage('user', text);
    setMode('thinking', 'PROCESSING', 'Your local AI model is interpreting your request...');
    try {
      const result = await api('/command', {method: 'POST', json: {text}});
      addMessage('assistant', result.reply);
      await Promise.allSettled([refreshPending(), refreshActivity()]);
      await refreshHistory().catch(() => {});
      if (/^\s*Approval required for\b/i.test(String(result.reply || ''))) {
        setMode('idle', 'APPROVAL REQUIRED', 'Review the request in the Approvals panel.');
      } else {
        speak(result.reply);
      }
    } catch (error) {
      setMode('error', 'COMMAND FAILED', error.message);
      showToast(error.message, true);
      addMessage('assistant', 'Command failed: ' + error.message);
    } finally {
      setBusy(false);
    }
  }
  // M13_BROWSER_CONTROL: always-available emergency stop for the research task.
  const stopBrowseButton = document.createElement('button');
  stopBrowseButton.type = 'button';
  stopBrowseButton.textContent = 'STOP BROWSING';
  stopBrowseButton.title = 'Request JARVIS to stop research in extension-created Chrome tabs';
  stopBrowseButton.className = 'button button-outline';
  stopBrowseButton.style.borderColor = '#e78888';
  stopBrowseButton.style.color = '#f3a6a6';
  sendButton.parentElement.insertBefore(stopBrowseButton, sendButton);
  stopBrowseButton.addEventListener('click', async () => {
    stopBrowseButton.disabled = true;
    try {
      const data = await api('/browser-stop', {method: 'POST'});
      showToast(data.message || 'Browser stop requested.');
    } catch (error) {
      showToast('Browser stop failed: ' + error.message, true);
    } finally {
      stopBrowseButton.disabled = false;
    }
  });

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
      stopSpeech();
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
      stopSpeech();
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
            // JARVIS_RESEARCH_SPEECH_V1: Speak after approved browser research finishes.
            if (approved && item.kind === 'browser_research') {
              const report = String(outcome.reply || '');
              let spoken;
              if (/^Action failed:/i.test(report)) {
                spoken = 'Sir, the browser research failed. Please check the dashboard for details.';
              } else if (/^Research stopped early/i.test(report) || /^Browser research was stopped/i.test(report)) {
                spoken = 'Sir, the research was stopped. Any partial findings are in your dashboard.';
              } else if (/^Browser research found no readable pages/i.test(report)) {
                spoken = 'Sir, I could not retrieve readable research pages. Please review the dashboard.';
              } else {
                const highlights = report.split(/\r?\n/)
                  .filter(line => /^\s*[-*]\s+/.test(line))
                  .slice(0, 2)
                  .map(line => line.replace(/^\s*[-*]\s+/, '')
                    .replace(/\[([^\]]+)\]\(https?:\/\/[^)]+\)/g, '$1')
                    .replace(/https?:\/\/\S+/g, '')
                    .replace(/[*_`#]/g, '')
                    .replace(/\s+/g, ' ').trim().slice(0, 210))
                  .filter(Boolean);
                spoken = highlights.length
                  ? 'Sir, the research is complete. Here are two highlights. ' +
                    highlights.join('. ') + '. The full report and sources are in your dashboard.'
                  : 'Sir, the research is complete. I have placed the findings and source links in your dashboard.';
              }
              speak(spoken);
            }
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
  let telemetryBusy = false;
  function displayPercent(kind, value) {
    const valid = typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100;
    const display = valid ? Math.round(value) : '—';
    $(kind + '-value').textContent = String(display);
    $(kind + '-unit').hidden = !valid;
    $(kind + '-bar').style.width = valid ? `${value}%` : '0%';
    const progress = $(kind + '-progress');
    if (valid) {
      progress.setAttribute('aria-valuenow', String(Math.round(value)));
      progress.removeAttribute('aria-valuetext');
    } else {
      progress.removeAttribute('aria-valuenow');
      progress.setAttribute('aria-valuetext', 'Not available');
    }
  }
  function formatGib(number) {
    return typeof number === 'number' && Number.isFinite(number) ? number.toFixed(1) + ' GiB' : null;
  }
  function applyTelemetry(data) {
    const cpu = data.cpu || {};
    const memory = data.memory || {};
    const gpu = data.gpu || {};
    displayPercent('cpu', cpu.percent);
    displayPercent('ram', memory.percent);
    displayPercent('gpu', gpu.percent);
    const ramUsed = formatGib(memory.used_gib);
    const ramTotal = formatGib(memory.total_gib);
    $('ram-detail').textContent = ramUsed && ramTotal ? `${ramUsed} / ${ramTotal} in use` : 'RAM reading unavailable';
    const gpuMemUsed = formatGib(gpu.memory_used_gib);
    const gpuMemTotal = formatGib(gpu.memory_total_gib);
    $('gpu-detail').textContent = gpuMemUsed && gpuMemTotal ? `${gpuMemUsed} / ${gpuMemTotal} VRAM` : 'GPU utilization unavailable';
    const tempOk = typeof gpu.temperature_c === 'number' && Number.isFinite(gpu.temperature_c);
    $('temp-value').textContent = tempOk ? String(Math.round(gpu.temperature_c)) : '—';
    $('temp-unit').hidden = !tempOk;
    $('temp-detail').textContent = gpu.name || 'GPU temperature unavailable';
    const state = data.status || 'unavailable';
    const badge = $('telemetry-status');
    badge.querySelector('.led').className = 'led ' + (state === 'ready' ? 'ok' : state === 'partial' ? 'warn' : 'fail');
    badge.lastChild.textContent = state === 'ready' ? ' Live sensors' : state === 'partial' ? ' Partial sensors' : ' Unavailable';
    $('telemetry-source').textContent = data.message || 'Host metrics unavailable.';
    $('telemetry-updated').textContent = data.sampled_at ? 'SAMPLED ' + new Date(data.sampled_at * 1000).toLocaleTimeString() : 'NOT SAMPLED';
  }
  async function refreshTelemetry() {
    if (telemetryBusy || document.hidden) return;
    telemetryBusy = true;
    try {
      const data = await api('/system-metrics');
      applyTelemetry(data);
    } catch (error) {
      applyTelemetry({status: 'unavailable', message: 'Windows host sensor request failed.'});
    } finally {
      telemetryBusy = false;
    }
  }
  $('refresh-telemetry').addEventListener('click', () => refreshTelemetry());
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshTelemetry(); });
  setInterval(refreshTelemetry, 7500);

  function refreshAll() {
    refreshStatus();
    refreshTelemetry();
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
    stopSpeech();
  });
})();
