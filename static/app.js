const form = document.querySelector('#chat-form');
const input = document.querySelector('#question');
const messages = document.querySelector('#messages');
const welcome = document.querySelector('#welcome');
const statusLine = document.querySelector('#status');
const reset = document.querySelector('#reset');
let busy = false;

function status(text = '', error = false) {
  statusLine.textContent = text;
  statusLine.classList.toggle('error', error);
}
function setBusy(value) {
  busy = value;
  document.querySelectorAll('button').forEach(button => button.disabled = value);
  input.disabled = value;
  form.setAttribute('aria-busy', String(value));
}
function addMessage(role, text) {
  const node = document.createElement('article');
  node.className = `message ${role}`;
  const label = document.createElement('div');
  label.className = 'message-label';
  label.textContent = role === 'user' ? 'YOU' : 'WEATHERLY';
  const body = document.createElement('div');
  body.className = 'message-body';
  body.textContent = text;
  node.append(label, body);
  messages.append(node);
  welcome.hidden = true;
  node.scrollIntoView({block: 'end'});
  return node;
}
async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? {} : {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Unable to connect. Please try again.');
  return data;
}
async function send(question) {
  if (busy || !question.trim()) return;
  question = question.trim();
  setBusy(true);
  const node = addMessage('user', question);
  input.value = '';
  input.style.height = 'auto';
  status('Checking the forecast… This can take a moment.');
  try {
    const data = await api('/api/chat', {message: question});
    addMessage('assistant', data.answer);
    status();
  } catch (error) {
    node.remove();
    welcome.hidden = messages.children.length > 0;
    input.value = question;
    status(error.message, true);
  } finally {
    setBusy(false);
    input.focus();
  }
}
form.addEventListener('submit', event => {event.preventDefault(); send(input.value);});
input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {event.preventDefault(); send(input.value);}
});
input.addEventListener('input', () => {input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 130)}px`;});
document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => send(button.dataset.question)));
reset.addEventListener('click', async () => {
  if (busy) return;
  setBusy(true);
  try {
    await api('/api/reset', {});
    messages.replaceChildren(); welcome.hidden = false; status(); input.value = '';
  } catch (error) {status(error.message, true);}
  finally {setBusy(false); input.focus();}
});
setBusy(true);
api('/api/session').then(data => {
  if (!data.configured) status('Add your API key to the server environment to start chatting.', true);
  else if (data.turns) status('Your earlier conversation is still active. Start a new chat to reset it.');
}).catch(error => status(error.message, true)).finally(() => setBusy(false));
