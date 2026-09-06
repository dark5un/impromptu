// impromptu studio UI: productions, voice-following prompter, render queue.
// Plain ES modules, no bundler, no npm (per the plan's web-UI constraint).
import {
  computeSpeechRecognitionTokenIndex,
  tokenize,
} from './vendor/speech-matcher.js';

const $ = (id) => document.getElementById(id);

let socket = null;
let recognition = null;
let reference = [];      // tokenized script from the server
let tokenIndex = 0;      // last matched token index
let following = false;
let current = null;      // production name
let resyncArmed = false; // next utterance searches the whole script

// ── productions ───────────────────────────────────────────────────────────────

async function refreshProductions() {
  const response = await fetch('/api/productions');
  const productions = await response.json();
  $('productions').replaceChildren(
    ...productions.map(({ name }) => {
      const item = document.createElement('li');
      const open = document.createElement('button');
      open.textContent = `Open ${name}`;
      open.onclick = () => connectPrompter(name);
      const render = document.createElement('button');
      render.textContent = 'Render';
      render.onclick = () => startRender(name);
      item.append(open, ' ', render);
      return item;
    }),
  );
}

// ── prompter rendering ────────────────────────────────────────────────────────

/**
 * Paint the script with everything up to `tokenIndex` marked as spoken, so the
 * reading position is visible rather than implied by scroll offset alone.
 */
function paintScript() {
  const spoken = document.createElement('span');
  spoken.className = 'spoken';
  const upcoming = document.createElement('span');

  let split = 0;
  for (const element of reference) {
    if (element.index <= tokenIndex) split += element.value.length;
    else break;
  }
  const text = reference.map((e) => e.value).join('');
  spoken.textContent = text.slice(0, split);
  upcoming.textContent = text.slice(split);
  $('prompt').replaceChildren(spoken, upcoming);

  // Keep the reading position in view. `nearest` avoids yanking the page when
  // the word is already visible.
  spoken.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function setStatus(state) {
  const mode = state.following ? 'following your voice' : 'manual';
  $('state').textContent =
    `${current}: ${state.paused ? 'paused' : 'playing'} · ${mode} · ` +
    `speed ${Number(state.speed).toFixed(1)} · token ${state.position}`;
}

// ── socket ────────────────────────────────────────────────────────────────────

function send(action, extra = {}) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ action, ...extra }));
  }
}

async function connectPrompter(name) {
  socket?.close();
  current = name;
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  socket = new WebSocket(
    `${protocol}://${location.host}/ws/teleprompter/${encodeURIComponent(name)}`,
  );
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    if (message.type === 'error') {
      $('prompt').textContent = message.detail;
      return;
    }
    if (message.type === 'ready') {
      // The server sends the script; the browser does the matching.
      reference = tokenize(message.script || '');
      tokenIndex = message.position ?? 0;
      paintScript();
    }
    if (message.type === 'state' || message.type === 'ready') {
      following = Boolean(message.following);
      if (message.type === 'state') {
        tokenIndex = message.position ?? tokenIndex;
        paintScript();
      }
      setStatus(message);
    }
  };
}

// ── voice following ───────────────────────────────────────────────────────────

/**
 * Start Web Speech recognition and report matched positions to the server.
 *
 * Recognition is `continuous` with `interimResults` so the position updates
 * while a sentence is still being spoken, not only at each pause. Matching uses
 * the vendored Levenshtein matcher, which is what survives going off script.
 */
function startFollowing() {
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    $('voice-note').textContent =
      'Voice following needs the Web Speech API (Chrome). Use manual speed instead.';
    return;
  }
  if (recognition) return;

  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = navigator.language || 'en-US';

  recognition.onresult = (event) => {
    // Only the newest result matters; earlier ones are already reflected in
    // tokenIndex, and re-matching them would drag the position backwards.
    const result = event.results[event.results.length - 1];
    const heard = result[0]?.transcript ?? '';
    if (!heard.trim()) return;
    const next = computeSpeechRecognitionTokenIndex(
      heard, reference, tokenIndex,
      // Resync: for this one utterance widen the window to the whole script so
      // a reader who fell behind (or jumped ahead) is brought back to where
      // they actually are. One-shot — it clears after use.
      resyncArmed ? 0 : tokenIndex,
    );
    resyncArmed = false;
    if (next !== tokenIndex) {
      tokenIndex = next;
      paintScript();
      send('voice', { position: tokenIndex });
    }
  };

  recognition.onerror = (event) => {
    $('voice-note').textContent = `speech recognition: ${event.error}`;
  };
  // Chrome stops recognition on silence; restart while still following so a
  // pause mid-take does not silently end following.
  recognition.onend = () => {
    if (following && recognition) recognition.start();
  };

  recognition.start();
  $('voice-note').textContent = 'listening — manual speed or seek overrides it';
  send('follow');
}

function stopFollowing() {
  if (!recognition) return;
  const stopping = recognition;
  recognition = null; // cleared first so onend does not restart it
  stopping.onend = null;
  stopping.stop();
  $('voice-note').textContent = 'voice following off';
}

// ── render queue ──────────────────────────────────────────────────────────────

async function startRender(name) {
  const response = await fetch(
    `/api/productions/${encodeURIComponent(name)}/render`,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ threads: 4 }),
    },
  );
  if (!response.ok) {
    alert((await response.json()).detail || 'Could not start render');
    return;
  }
  await refreshRenders();
}

async function refreshRenders() {
  const response = await fetch('/api/renders');
  if (!response.ok) return;
  const jobs = await response.json();
  $('renders').replaceChildren(
    ...jobs.map((job) => {
      const item = document.createElement('li');
      const percent = Number(job.percent || 0).toFixed(0);
      item.textContent =
        `${job.production} · ${job.state} · ${percent}%` +
        (job.error ? ` · ${job.error}` : '') +
        (job.output ? ` · ${job.output}` : '');
      return item;
    }),
  );
}

// Poll while anything is in flight. A websocket for progress would be nicer,
// but polling a local endpoint every second is honest and has no reconnect
// semantics to get wrong.
setInterval(refreshRenders, 1000);

// ── wiring ────────────────────────────────────────────────────────────────────

$('pause').onclick = () => send('pause');
$('resume').onclick = () => send('resume');
$('follow').onclick = () => startFollowing();
$('unfollow').onclick = () => {
  stopFollowing();
  // Re-asserting speed is what flips `following` off server-side.
  send('speed', { speed: 1.5 });
};
$('resync').onclick = () => {
  // Arm the next recognition result to search the whole script, so the
  // prompter jumps to wherever the reader actually is. Useful after being
  // pulled away, or reading from the middle.
  resyncArmed = true;
  $('voice-note').textContent =
    'resync armed — say your current line to jump the prompter to it';
};

$('new-production').onsubmit = async (event) => {
  event.preventDefault();
  const name = $('name').value;
  const response = await fetch(`/api/productions/${encodeURIComponent(name)}`, {
    method: 'POST',
  });
  if (!response.ok) {
    alert((await response.json()).detail || 'Could not create production');
    return;
  }
  $('name').value = '';
  await refreshProductions();
};

fetch('/healthz')
  .then((r) => r.json())
  .then((data) => {
    $('health').textContent = `studio ${data.status}`;
  });
refreshProductions();
refreshRenders();
