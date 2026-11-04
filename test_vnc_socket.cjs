// The Cockpit channel may close synchronously; WebSocket consumers require an async event.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('cockpit_vnc/secure-vnc.js', 'utf8');
const classSource = source.slice(source.indexOf('class CockpitSocket'), source.indexOf('\nfunction stop'));
async function test() {
  let handlers;
  const context = vm.createContext({queueMicrotask, Uint8Array, cockpit: {channel() {
    handlers = {};
    return {addEventListener(name, callback) {handlers[name] = callback;},
      close() {handlers.close(null, {});}, send() {}};
  }}});
  const Socket = vm.runInContext(classSource + '\nCockpitSocket', context);
  const socket = new Socket(5910);
  socket.readyState = 1;
  let events = 0;
  socket.onclose = event => {events++; assert.equal(event.wasClean, true);};
  socket.close();
  assert.equal(events, 0, 'close event must not run inside close()');
  await Promise.resolve();
  assert.equal(events, 1, 'emit exactly one close event');
  socket.close();
  handlers.close(null, {});
  await Promise.resolve();
  assert.equal(events, 1, 'duplicate transport close must be ignored');
  console.log('3/3 VNC socket lifecycle checks passed');
}
test().catch(error => {console.error(error); process.exitCode = 1;});
