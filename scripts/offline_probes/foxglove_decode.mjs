// Drive the mission console's own ros.mjs Bridge against a live foxglove_bridge
// and report whether each topic arrives and decodes -- the 3D view's data path,
// with no browser.  Needs Node >= 22 (global WebSocket; install via nvm).
//
//   node foxglove_decode.mjs <path/to/ros.mjs> ws://localhost:8765 /poses /tf ...
const [, , modPath, url, ...topics] = process.argv;
const { Bridge } = await import(modPath);
const b = new Bridge(url);
const got = {};
for (const t of topics) {
  b.subscribe(t, (msg) => {
    if (!got[t]) { got[t] = msg; console.log('DECODED', t, JSON.stringify(msg).slice(0, 200)); }
  });
}
b.connect();
setTimeout(() => {
  console.log('state', b.state, '| messages', b.rx, '| error', b.error || '-');
  for (const c of b.channels.values()) {
    if (topics.includes(c.topic)) console.log('channel', c.topic, c.encoding, c.decodeError || 'decodes cleanly');
  }
  const missing = topics.filter((t) => !got[t]);
  console.log(missing.length ? `MISSING: ${missing.join(' ')}` : 'all topics received');
  process.exit(missing.length ? 1 : 0);
}, 8000);
