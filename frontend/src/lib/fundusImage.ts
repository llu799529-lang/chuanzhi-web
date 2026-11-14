/**
 * 眼底「专业阅片」的图像处理：纯函数，输入输出都是 RGBA 字节（与 canvas ImageData.data 排列相同），可脱离浏览器测试。
 *
 *  · 增强：对亮度做 CLAHE（对比度受限的自适应直方图均衡），色度保持不变——颜色不失真，渗出、出血、微血管瘤更清楚；
 *  · 无赤光：只取绿色通道再做 CLAHE，输出灰度。眼底照相的「无赤光（red-free）」就是滤掉红光：
 *    出血、微血管瘤和血管在绿光下最暗、与背景对比最强，是眼科医生找微小病灶的常用看法；
 *  · 视网膜外的黑色背景不参与直方图统计，否则四角的大片黑色会把均衡结果拉偏、把噪声放大。
 * 这些处理只改变显示，不参与、也不改变分级。
 */
export type Pixels = Uint8ClampedArray;

/** 亮度低于此值视为视网膜外的黑色背景 */
export const BG_LEVEL = 12;

export function luminance(px: Pixels): Uint8ClampedArray {
  const n = px.length >> 2;
  const y = new Uint8ClampedArray(n);
  for (let i = 0; i < n; i++) {
    const j = i << 2;
    y[i] = (px[j] * 299 + px[j + 1] * 587 + px[j + 2] * 114) / 1000;
  }
  return y;
}

export function retinaMask(y: Uint8ClampedArray): Uint8Array {
  const m = new Uint8Array(y.length);
  for (let i = 0; i < y.length; i++) m[i] = y[i] > BG_LEVEL ? 1 : 0;
  return m;
}

export interface ClaheOptions {
  /** 每个方向分块数 */
  tiles?: number;
  /** 截断倍数：直方图每一格最多为平均频数的 clip 倍，越大对比越强、噪声也越明显 */
  clip?: number;
  /** 0 = 不参与统计、原样输出 */
  mask?: Uint8Array;
}

/** CLAHE：分块统计直方图 → 截断并均匀回填 → 累计分布作映射表 → 块与块之间双线性插值，避免块边界。 */
export function clahe(gray: Uint8ClampedArray, w: number, h: number, opts: ClaheOptions = {}): Uint8ClampedArray {
  const tiles = Math.max(1, Math.round(opts.tiles ?? 8));
  const clip = opts.clip ?? 2.5;
  const mask = opts.mask;
  const tx = Math.min(tiles, w);
  const ty = Math.min(tiles, h);
  const cw = w / tx;
  const ch = h / ty;
  const luts = new Uint8ClampedArray(tx * ty * 256);
  const hist = new Float64Array(256);
  for (let by = 0; by < ty; by++) {
    for (let bx = 0; bx < tx; bx++) {
      hist.fill(0);
      let count = 0;
      for (let y = Math.floor(by * ch), y1 = Math.floor((by + 1) * ch); y < y1; y++) {
        for (let x = Math.floor(bx * cw), x1 = Math.floor((bx + 1) * cw); x < x1; x++) {
          const i = y * w + x;
          if (mask && !mask[i]) continue;
          hist[gray[i]]++;
          count++;
        }
      }
      const base = (by * tx + bx) * 256;
      if (!count) {
        for (let v = 0; v < 256; v++) luts[base + v] = v;
        continue;
      }
      const limit = Math.max(1, (clip * count) / 256);
      let excess = 0;
      for (let v = 0; v < 256; v++) {
        if (hist[v] > limit) {
          excess += hist[v] - limit;
          hist[v] = limit;
        }
      }
      const add = excess / 256;
      let cdf = 0;
      for (let v = 0; v < 256; v++) {
        cdf += hist[v] + add;
        luts[base + v] = Math.round((cdf / count) * 255);
      }
    }
  }
  const out = new Uint8ClampedArray(w * h);
  for (let y = 0; y < h; y++) {
    const fy = (y + 0.5) / ch - 0.5;
    const y0 = Math.max(0, Math.min(ty - 1, Math.floor(fy)));
    const y1 = Math.min(ty - 1, y0 + 1);
    const wy = Math.max(0, Math.min(1, fy - y0));
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const v = gray[i];
      if (mask && !mask[i]) {
        out[i] = v;
        continue;
      }
      const fx = (x + 0.5) / cw - 0.5;
      const x0 = Math.max(0, Math.min(tx - 1, Math.floor(fx)));
      const x1 = Math.min(tx - 1, x0 + 1);
      const wx = Math.max(0, Math.min(1, fx - x0));
      const a = luts[(y0 * tx + x0) * 256 + v];
      const b = luts[(y0 * tx + x1) * 256 + v];
      const c = luts[(y1 * tx + x0) * 256 + v];
      const d = luts[(y1 * tx + x1) * 256 + v];
      out[i] = (a * (1 - wx) + b * wx) * (1 - wy) + (c * (1 - wx) + d * wx) * wy;
    }
  }
  return out;
}

/** 增强：亮度做 CLAHE，色度（YCbCr 的 Cb / Cr）不变 */
export function enhance(px: Pixels, w: number, h: number): Uint8ClampedArray {
  const y = luminance(px);
  const y2 = clahe(y, w, h, { mask: retinaMask(y), clip: 2.2 });
  const out = new Uint8ClampedArray(px.length);
  for (let i = 0, j = 0; i < y.length; i++, j += 4) {
    const r = px[j];
    const g = px[j + 1];
    const b = px[j + 2];
    const cb = -0.168736 * r - 0.331264 * g + 0.5 * b;
    const cr = 0.5 * r - 0.418688 * g - 0.081312 * b;
    const l = y2[i];
    out[j] = l + 1.402 * cr;
    out[j + 1] = l - 0.344136 * cb - 0.714136 * cr;
    out[j + 2] = l + 1.772 * cb;
    out[j + 3] = px[j + 3];
  }
  return out;
}

/** 无赤光：绿色通道 + CLAHE，灰度输出；背景保持黑色 */
export function redFree(px: Pixels, w: number, h: number): Uint8ClampedArray {
  const n = px.length >> 2;
  const g = new Uint8ClampedArray(n);
  for (let i = 0; i < n; i++) g[i] = px[(i << 2) + 1];
  const mask = retinaMask(luminance(px));
  const g2 = clahe(g, w, h, { mask, clip: 3 });
  const out = new Uint8ClampedArray(px.length);
  for (let i = 0, j = 0; i < n; i++, j += 4) {
    const v = mask[i] ? g2[i] : 0;
    out[j] = v;
    out[j + 1] = v;
    out[j + 2] = v;
    out[j + 3] = px[j + 3];
  }
  return out;
}
