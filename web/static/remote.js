// Phone remote: forwards control actions to the teleprompter socket.
// The pairing token travels in the query string so the socket can be gated the
// same way the /remote page itself is.
const token = new URLSearchParams(location.search).get('token') ?? '';
const production = new URLSearchParams(location.search).get('production') ?? 'default';
const state = document.getElementById('state');

const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
const socket = new WebSocket(
  `${protocol}://${location.host}/ws/teleprompter/${encodeURIComponent(production)}` +
  `?token=${encodeURIComponent(token)}`,
);

socket.onopen = () => { state.textContent = 'connected'; };
socket.onclose = (event) => {
  // 1008 is the policy-violation code the server uses for a rejected token.
  state.textContent = event.code === 1008 ? 'pairing rejected — re-run impromptu pair' : 'disconnected';
};
socket.onmessage = ({data}) => {
  const message = JSON.parse(data);
  if (message.type === 'state' || message.type === 'ready') {
    state.textContent = `${message.paused ? 'paused' : 'playing'} · line ${message.position}`;
  }
};

const send = (action, extra = {}) => {
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({action, ...extra}));
  }
};

let position = 0;
let speed = 1.5;
document.getElementById('toggle').onclick = () => send('toggle');
document.getElementById('back').onclick = () => send('seek', {position: (position = Math.max(0, position - 1))});
document.getElementById('fwd').onclick = () => send('seek', {position: (position += 1)});
document.getElementById('slower').onclick = () => send('speed', {speed: (speed = Math.max(0.3, speed - 0.3))});
document.getElementById('faster').onclick = () => send('speed', {speed: (speed = Math.min(10, speed + 0.3))});
