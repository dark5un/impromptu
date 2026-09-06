const $ = (id) => document.getElementById(id);
let socket;

async function refreshProductions() {
  const response = await fetch('/api/productions');
  const productions = await response.json();
  $('productions').replaceChildren(...productions.map(({name}) => {
    const item = document.createElement('li');
    const button = document.createElement('button');
    button.textContent = `Open ${name}`;
    button.onclick = () => connectPrompter(name);
    item.append(button);
    return item;
  }));
}

async function connectPrompter(name) {
  socket?.close();
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  socket = new WebSocket(`${protocol}://${location.host}/ws/teleprompter/${encodeURIComponent(name)}`);
  socket.onmessage = ({data}) => {
    const state = JSON.parse(data);
    if (state.type === 'state' || state.type === 'ready') {
      $('state').textContent = `${name}: ${state.paused ? 'paused' : 'playing'} · position ${state.position}`;
    }
  };
}

$('pause').onclick = () => socket?.send(JSON.stringify({action: 'pause'}));
$('resume').onclick = () => socket?.send(JSON.stringify({action: 'resume'}));
$('new-production').onsubmit = async (event) => {
  event.preventDefault();
  const name = $('name').value;
  const response = await fetch(`/api/productions/${encodeURIComponent(name)}`, {method: 'POST'});
  if (!response.ok) return alert((await response.json()).detail || 'Could not create production');
  $('name').value = '';
  await refreshProductions();
};

fetch('/healthz').then((r) => r.json()).then((data) => { $('health').textContent = `studio ${data.status}`; });
refreshProductions();
