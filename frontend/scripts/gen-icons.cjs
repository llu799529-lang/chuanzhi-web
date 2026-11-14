// 零依赖生成 favicon.ico / apple-touch-icon.png
// 纯手写 PNG（zlib 已在 node 标准库）+ ICO 容器封装，不依赖 sharp / canvas。
// 图形照 frontend/public/favicon.svg 的 9 层旋转叠片 + 医疗十字重绘。
const fs = require("fs");
const zlib = require("zlib");
const path = require("path");

const PUBLIC = path.resolve(__dirname, "..", "public");

// ---------- 渐变（与 favicon.svg 中的 stop 一致）----------
const G = {
  d: ["#0a2440", "#1a4a76", "#4f8ec2", "#dbeefd", "#3f7cb0", "#14395c", "#0c2844"],
  k: ["#0a2440", "#1a4a76", "#4f8ec2", "#7fa8cc", "#3f7cb0", "#14395c", "#0c2844"],
  m: ["#7db0d8", "#aacfeb", "#ffffff", "#6fa2cb", "#93bfe0"],
  l: ["#cfe4f6", "#edf6fd", "#ffffff", "#bcd8ee", "#dcecf9"],
  c: ["#cfe0f0", "#c4d9eb", "#b8d0e6", "#c9ddee"],
};
const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
const ramp = (list) => list.map(hex);

// 沿对角线取渐变色
function sample(stops, t) {
  const n = stops.length - 1;
  const x = Math.min(0.9999, Math.max(0, t)) * n;
  const i = Math.floor(x);
  const f = x - i;
  const a = stops[i];
  const b = stops[Math.min(n, i + 1)];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}
const GD = ramp(G.d), GK = ramp(G.k), GM = ramp(G.m), GL = ramp(G.l), GC = ramp(G.c);

// ---------- 几何工具（SVG 用户坐标 20..147）----------
function rot(px, py, deg, cx, cy) {
  const r = (deg * Math.PI) / 180;
  const dx = px - cx;
  const dy = py - cy;
  return [cx + dx * Math.cos(r) - dy * Math.sin(r), cy + dx * Math.sin(r) + dy * Math.cos(r)];
}

function inRoundRect(x, y, x0, y0, x1, y1, r) {
  if (x < x0 || x > x1 || y < y0 || y > y1) return false;
  const cx = Math.min(Math.max(x, x0 + r), x1 - r);
  const cy = Math.min(Math.max(y, y0 + r), y1 - r);
  const dx = x - cx;
  const dy = y - cy;
  return dx * dx + dy * dy <= r * r || (x >= x0 + r && x <= x1 - r) || (y >= y0 + r && y <= y1 - r);
}

// 一块叠片的判定（已含旋转与平移）
function plate(x, y, deg, tx, ty) {
  const [ux, uy] = rot(x - tx, y - ty, -deg, 100, 100);
  return inRoundRect(ux, uy, 53, 53, 147, 147, 26);
}

// ---------- 4x4 超采样渲染 ----------
const SS = 4;
function render(size) {
  const px = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let r = 0, g = 0, b = 0, a = 0;
      for (let sy = 0; sy < SS; sy++) {
        for (let sx = 0; sx < SS; sx++) {
          const u = 20 + ((x + (sx + 0.5) / SS) / size) * 127;
          const v = 26 + ((y + (sy + 0.5) / SS) / size) * 127;
          const t = Math.min(1, Math.max(0, ((u - 53) + (v - 53)) / 188));

          let col = null;
          // 自下而上叠：浅片 → 亮片 → 主片
          if (plate(u, v, -18, -16, -16)) col = sample(GL, t);
          if (plate(u, v, -9, -8, -8)) col = sample(GM, t);
          if (plate(u, v, 0, 0, 0)) col = sample(GK, t);

          // 主片上的医疗十字（渐变 fill=url(#c)）
          if (plate(u, v, 0, 0, 0)) {
            const inV = inRoundRect(u, v, 92, 68, 108, 132, 8);
            const inH = inRoundRect(u, v, 68, 92, 132, 108, 8);
            if (inV || inH) col = sample(GC, t);
          }

          if (col) {
            r += col[0];
            g += col[1];
            b += col[2];
            a += 255;
          }
        }
      }
      const n = SS * SS;
      const i = (y * size + x) * 4;
      const cov = a / 255;
      px[i] = cov ? Math.round(r / cov) : 0;
      px[i + 1] = cov ? Math.round(g / cov) : 0;
      px[i + 2] = cov ? Math.round(b / cov) : 0;
      px[i + 3] = Math.round(a / n);
    }
  }
  return px;
}

// ---------- PNG ----------
const TBL = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c;
  }
  return t;
})();
const crc32 = (buf) => {
  let c = -1;
  for (let i = 0; i < buf.length; i++) c = TBL[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ -1) >>> 0;
};
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}
function encodePNG(size, rgba) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  const raw = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y++) rgba.copy(raw, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}
function buildICO(entries) {
  const head = Buffer.alloc(6);
  head.writeUInt16LE(0, 0);
  head.writeUInt16LE(1, 2);
  head.writeUInt16LE(entries.length, 4);
  const dirs = [];
  let off = 6 + entries.length * 16;
  for (const e of entries) {
    const d = Buffer.alloc(16);
    d[0] = e.size >= 256 ? 0 : e.size;
    d[1] = e.size >= 256 ? 0 : e.size;
    d.writeUInt16LE(1, 4);
    d.writeUInt16LE(32, 6);
    d.writeUInt32LE(e.png.length, 8);
    d.writeUInt32LE(off, 12);
    off += e.png.length;
    dirs.push(d);
  }
  return Buffer.concat([head, ...dirs, ...entries.map((e) => e.png)]);
}

const sizes = [16, 32, 48];
const entries = sizes.map((s) => ({ size: s, png: encodePNG(s, render(s)) }));
const ico = buildICO(entries);
fs.writeFileSync(path.join(PUBLIC, "favicon.ico"), ico);

const apple = encodePNG(180, render(180));
fs.writeFileSync(path.join(PUBLIC, "apple-touch-icon.png"), apple);

console.log("[icons] favicon.ico        ", ico.length, "B  (16/32/48)");
console.log("[icons] apple-touch-icon.png", apple.length, "B  (180x180)");
