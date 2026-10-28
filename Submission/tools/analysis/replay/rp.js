// Engine-2.0 replay reader: load(wasmPath) -> E; openReplay(E, bytes) -> G {size}; read(E, G, pos) -> state.
// Snapshot layout (engine 2.0.0): round u32@8; champions count u32@172, data @196 stride 420
// (idx@4 team@8 type@12 x@16 y@20 hp f32@24 max f32@28 alive@32 gold@36 gems@40 kills@44); camps count u32@176,
// data @6916 stride 28 (idx@4 type@12 x@16 y@20 hp f32@24; dead camps have x = -1).
const fs = require('fs');
const { WASI } = require('wasi');
function load(path) {
  const wasi = new WASI({ version: 'preview1', args: [], env: {}, returnOnExit: true });
  const inst = new WebAssembly.Instance(new WebAssembly.Module(fs.readFileSync(path)), { wasi_snapshot_preview1: wasi.wasiImport });
  wasi.initialize(inst);
  return { ex: inst.exports, mem: () => new DataView(inst.exports.memory.buffer) };
}
function cstr(E, p) {
  const b = new Uint8Array(E.ex.memory.buffer); let s = '';
  for (let i = p; b[i]; i++) s += String.fromCharCode(b[i]);
  return s;
}
function openReplay(E, bytes) {
  const ex = E.ex;
  const check = rc => { if (rc !== 0) throw new Error('engine error ' + rc + ': ' + cstr(E, ex.GetLastErrorMsg())); };
  const p = ex.Engine_Malloc(bytes.length);
  new Uint8Array(ex.memory.buffer, p, bytes.length).set(bytes);
  const out = ex.Engine_Malloc(64);
  check(ex.Game_FromReplayFileBytes(p, bytes.length, out));
  const h = E.mem().getBigUint64(out, true);
  check(ex.Game_Visualiser_Timeline_GetMain(h, out));
  const tl = E.mem().getBigUint64(out, true);
  check(ex.Game_Visualiser_Timeline_Info(h, tl, out, out + 8, out + 16));
  const size = Number(E.mem().getBigUint64(out, true));
  const snap = Number(ex.Game_Visualiser_TimelineSnapshotSize ? ex.Game_Visualiser_TimelineSnapshotSize() : 65536);
  const buf = ex.Engine_Malloc(Math.max(snap, 65536));
  return { h, tl, size, buf, check };
}
function read(E, G, pos) {
  const ex = E.ex;
  G.check(ex.Game_Visualiser_Timeline_Seek(G.h, G.tl, pos, 0));
  G.check(ex.Game_Visualiser_ReadTimelineState(G.h, G.buf));
  const v = E.mem(), b = G.buf;
  const u = o => v.getUint32(b + o, true), i = o => v.getInt32(b + o, true), f = o => v.getFloat32(b + o, true);
  const champs = [], camps = [];
  const nc = u(172), nk = u(176);
  for (let k = 0; k < nc && k < 16; k++) {
    const o = 196 + k * 420;
    champs.push({ idx: u(o + 4), team: u(o + 8), type: u(o + 12), x: i(o + 16), y: i(o + 20), hp: f(o + 24), max: f(o + 28),
                  alive: !!u(o + 32), gold: u(o + 36), gems: u(o + 40), kills: u(o + 44) });
  }
  for (let k = 0; k < nk && k < 400; k++) {
    const o = 6916 + k * 28;
    camps.push({ idx: u(o + 4), type: u(o + 12), x: i(o + 16), y: i(o + 20), hp: f(o + 24) });
  }
  return { round: u(8), champs, camps };
}
module.exports = { load, openReplay, read };
