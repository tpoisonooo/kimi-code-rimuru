/* Rimuru idle skin widget for Kimi Code Web UI — mesh-puppet version.
 * Floating transparent canvas, bottom-right corner. Classic script, same-origin
 * assets — passes the server's CSP (no inline script/style).
 * Mesh: quadtree grid, contour-snapped; controls drive hem corners / hair tips /
 * boot fur / cuff fur via compact-falloff IDW; tassel is a strip-warped patch.
 * Static triangles are baked to an offscreen canvas once — only deforming
 * triangles are re-rendered per frame.
 */
(() => {
  "use strict";

  const BASE = "/rimuru-skin/";
  const VIEW = 0.5;      // display scale: 400x618 -> 200x309
  const STRIP = 2;
  // tassel strip-warp params (rimuru-skin scheme; bead+string texture is solid)
  const TASSEL = { x: 313, y: 247, w: 46, h: 84, amp_x: 4.0, amp_y: 0.5, period: 1.1, phase: 1.2, exp: 1.5 };

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function loadImage(src) {
    return new Promise((res, rej) => {
      const im = new Image();
      im.onload = () => res(im);
      im.onerror = () => rej(new Error("load failed: " + src));
      im.src = src;
    });
  }

  function smooth01(u) { return u <= 0 ? 0 : u >= 1 ? 1 : u * u * (3 - 2 * u); }

  function buildWeights(mesh) {
    const P = mesh.points, C = mesh.controls;
    const WTS = P.map(() => new Float64Array(C.length));
    for (let i = 0; i < P.length; i++) {
      let sum = 0;
      for (let j = 0; j < C.length; j++) {
        const cvx = P[C[j].vertex];
        const d = Math.hypot(P[i][0] - cvx[0], P[i][1] - cvx[1]);
        const w = d < C[j].radius ? smooth01(1 - d / C[j].radius) : 0;
        WTS[i][j] = w; sum += w;
      }
      if (sum > 0) for (let j = 0; j < C.length; j++) WTS[i][j] /= sum;
      for (let j = 0; j < C.length; j++) {
        if (!C[j].rigid) continue;
        const cvx = P[C[j].vertex];
        const d = Math.hypot(P[i][0] - cvx[0], P[i][1] - cvx[1]);
        if (d < C[j].radius) { WTS[i].fill(0); WTS[i][j] = 1; }
      }
    }
    return WTS;
  }

  function displaced(mesh, WTS, t) {
    const out = new Float64Array(mesh.points.length * 2);
    for (let i = 0; i < mesh.points.length; i++) {
      let dx = 0, dy = 0;
      for (let j = 0; j < mesh.controls.length; j++) {
        const w = WTS[i][j];
        if (w === 0) continue;
        const c = mesh.controls[j];
        const s = Math.sin(2 * Math.PI * t / c.period + c.phase);
        dx += w * c.amp_x * s; dy += w * c.amp_y * s;
      }
      out[i * 2] = mesh.points[i][0] + dx;
      out[i * 2 + 1] = mesh.points[i][1] + dy;
    }
    return out;
  }

  // affine src tri -> dst tri, [a,b,c,d,e,f] for ctx.transform
  function affineFwd(s, d) {
    const det = s[0][0] * (s[1][1] - s[2][1]) + s[1][0] * (s[2][1] - s[0][1]) + s[2][0] * (s[0][1] - s[1][1]);
    const solve = (o) => [
      (o[0] * (s[1][1] - s[2][1]) + o[1] * (s[2][1] - s[0][1]) + o[2] * (s[0][1] - s[1][1])) / det,
      (s[0][0] * (o[1] - o[2]) + s[1][0] * (o[2] - o[0]) + s[2][0] * (o[0] - o[1])) / det,
      (s[0][0] * (s[1][1] * o[2] - s[2][1] * o[1]) + s[1][0] * (s[2][1] * o[0] - s[0][1] * o[2]) + s[2][0] * (s[0][1] * o[1] - s[1][1] * o[0])) / det,
    ];
    const X = solve([d[0][0], d[1][0], d[2][0]]);
    const Y = solve([d[0][1], d[1][1], d[2][1]]);
    return [X[0], Y[0], X[1], Y[1], X[2], Y[2]];
  }

  function expandTri(d, pad) {
    const cx = (d[0][0] + d[1][0] + d[2][0]) / 3, cy = (d[0][1] + d[1][1] + d[2][1]) / 3;
    return d.map(([x, y]) => {
      const vx = x - cx, vy = y - cy, n = Math.hypot(vx, vy) || 1;
      return [x + vx / n * pad, y + vy / n * pad];
    });
  }

  function drawTri(ctx, img, s, d) {
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(d[0][0], d[0][1]); ctx.lineTo(d[1][0], d[1][1]); ctx.lineTo(d[2][0], d[2][1]);
    ctx.closePath();
    ctx.clip();
    const m = affineFwd(s, d);
    ctx.transform(m[0], m[1], m[2], m[3], m[4], m[5]);
    ctx.drawImage(img, 0, 0);
    ctx.restore();
  }

  async function main() {
    const mesh = await (await fetch(BASE + "mesh.json")).json();
    const [sprite, tassel] = await Promise.all([
      loadImage(BASE + "sprite_meshed.png"), loadImage(BASE + "tassel_patch.png")]);
    const WTS = buildWeights(mesh);

    // split triangles: static (baked once) vs dynamic (re-rendered per frame)
    const dyn = [], sta = [];
    for (const tri of mesh.tris) {
      const moving = tri.some(v => WTS[v].some(w => w > 0));
      (moving ? dyn : sta).push(tri);
    }
    const staCv = document.createElement("canvas");
    staCv.width = mesh.width; staCv.height = mesh.height;
    const staCtx = staCv.getContext("2d");
    for (const [a, b, c] of sta) {
      const s = [mesh.points[a], mesh.points[b], mesh.points[c]];
      drawTri(staCtx, sprite, s, expandTri(s.map(p => [...p]), 0.8));
    }

    const dpr = window.devicePixelRatio || 1;
    const cv = document.createElement("canvas");
    cv.width = Math.round(mesh.width * VIEW * dpr);
    cv.height = Math.round(mesh.height * VIEW * dpr);
    cv.style.cssText =
      "position:fixed;right:12px;bottom:0;z-index:9999;pointer-events:none;" +
      "width:" + mesh.width * VIEW + "px;height:" + mesh.height * VIEW + "px;";
    document.body.appendChild(cv);
    const ctx = cv.getContext("2d");
    const k = VIEW * dpr;

    function draw(t) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, cv.width, cv.height);
      ctx.setTransform(k, 0, 0, k, 0, 0);
      ctx.drawImage(staCv, 0, 0);
      const dp = displaced(mesh, WTS, t);
      for (const [a, b, c] of dyn) {
        const s = [mesh.points[a], mesh.points[b], mesh.points[c]];
        const d = expandTri([[dp[a * 2], dp[a * 2 + 1]], [dp[b * 2], dp[b * 2 + 1]], [dp[c * 2], dp[c * 2 + 1]]], 0.8);
        drawTri(ctx, sprite, s, d);
      }
      const ang = 2 * Math.PI * t / TASSEL.period + TASSEL.phase;
      const sx = Math.sin(ang), sy = Math.cos(ang);
      for (let j = 0; j < TASSEL.h; j += STRIP) {
        const hh = Math.min(STRIP, TASSEL.h - j);
        const w = Math.pow(j / (TASSEL.h - 1), TASSEL.exp);
        ctx.drawImage(tassel, 0, j, TASSEL.w, hh,
                      TASSEL.x + TASSEL.amp_x * w * sx, TASSEL.y + j + TASSEL.amp_y * w * sy,
                      TASSEL.w, hh);
      }
    }

    if (reduced) { draw(0); return; }
    let tPrev = null, tAcc = 0;
    function frame(now) {
      requestAnimationFrame(frame);
      const tSec = now / 1000;
      if (tPrev === null) tPrev = tSec;
      tAcc += tSec - tPrev;
      tPrev = tSec;
      draw(tAcc);
    }
    requestAnimationFrame(frame);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => { main().catch(() => {}); });
  } else {
    main().catch(() => {});
  }
})();
