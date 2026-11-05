// Open the console's mission window in headless Chrome and report what the
// 3D view actually got: websocket frames from foxglove_bridge, page errors,
// and the drone labels it draws ("cf1  1.20 m", "(est)" = onboard estimate).
// Talks to Chrome over the DevTools protocol; needs Node >= 22.
//
//   google-chrome --headless=new --remote-debugging-port=9333 ... &
//   node mission_view.mjs 9333 'http://localhost:8098/mission?m=crazyflie_shows/guard' [seconds]
const [, , cdpPort, url, secs = '12'] = process.argv;

const ver = await (await fetch(`http://127.0.0.1:${cdpPort}/json/version`)).json();
const ws = new WebSocket(ver.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let id = 0; const pending = new Map(); const errors = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
  if (m.method === 'Runtime.exceptionThrown') errors.push('exception: ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text).slice(0, 200));
  if (m.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(m.params.type)) {
    errors.push(`console.${m.params.type}: ` + m.params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 200));
  }
};
const send = (method, params = {}, sessionId) => new Promise((r) => {
  const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params, sessionId }));
});

const { result: { targetId } } = await send('Target.createTarget', { url: 'about:blank' });
const { result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true });
const s = (m, p) => send(m, p, sessionId);
await s('Runtime.enable'); await s('Page.enable');
// count what the page's WebSockets receive, before any page script runs
await s('Page.addScriptToEvaluateOnNewDocument', { source: `
  window.__ws = { open: 0, text: 0, binary: 0, urls: [], protocol: '' };
  const W = window.WebSocket;
  window.WebSocket = function (u, p) {
    const w = new W(u, p); window.__ws.urls.push(String(u));
    w.addEventListener('open', () => { window.__ws.open += 1; window.__ws.protocol = w.protocol; });
    w.addEventListener('message', (e) => { typeof e.data === 'string' ? window.__ws.text++ : window.__ws.binary++; });
    return w;
  };
  window.WebSocket.prototype = W.prototype; Object.assign(window.WebSocket, W);` });
await s('Page.navigate', { url });
await new Promise((r) => setTimeout(r, Number(secs) * 1000));

const ev = async (expr) => (await s('Runtime.evaluate', { expression: expr, returnByValue: true })).result.result.value;
const wsStats = await ev('JSON.stringify(window.__ws)');
const labels = await ev(`JSON.stringify([...new Set([...document.querySelectorAll('body *')]
  .filter((e) => e.children.length === 0 && /^(cf\\d+)\\s+-?\\d+\\.\\d\\d m/.test(e.textContent.trim()))
  .map((e) => e.textContent.trim()))])`);
const webgl = await ev(`(() => { try { return !!document.createElement('canvas').getContext('webgl2'); } catch (e) { return false; } })()`);
const bodyText = await ev(`document.body.innerText.slice(0, 300).replace(/\\s+/g, ' ')`);

console.log('page:', url);
console.log('webgl2:', webgl, '(false = the 2D fallback view, which draws no DOM labels)');
console.log('websocket:', wsStats);
console.log('drone labels:', labels);
console.log('page text:', bodyText);
console.log(errors.length ? 'page errors:\n  ' + [...new Set(errors)].slice(0, 10).join('\n  ') : 'page errors: none');
await send('Target.closeTarget', { targetId });
process.exit(0);
