/* ============================================================
   MedTriage 首页 · 救护车（高顶厢式急救车，三渲二）
   与 hospital.js 同一套材质：MeshToonMaterial 阶调 + 轮廓线
   坐标：车头朝 +z，车轮着地 y=0，车宽沿 x；摆放与警示灯动画由 hospital.js 负责
   ============================================================ */
(function (root) {
  "use strict";

  root.MTBuildAmbulance = function (THREE, kit) {
    var toon = kit.toon, flat = kit.flat, edges = kit.edges;
    var WHITE = 0xfbfcfd, RED = 0xe0472f, BLUE = 0x2c5aa0, GLASS = 0x34526d, GLASS_HI = 0x9cc0dd,
      FROST = 0xcfdce8, TRIM = 0x5d6b78, SEAM = 0xaebac6, TIRE = 0x2f3740, RIM = 0xd5dce2,
      RIM_IN = 0xa9b4bf, HUB = 0x7d8a97;
    var W = 2.04, HALF = W / 2, BEVEL = 0.05;
    var car = new THREE.Group();

    function add(m, x, y, z) { m.position.set(x, y, z); car.add(m); return m; }
    function bothSides(fn) { fn(1); fn(-1); }

    /* ---------- 车身：侧面轮廓挤出（高顶 + 斜风挡 + 圆鼻头 + 两个轮拱） ---------- */
    var p = new THREE.Shape();
    p.moveTo(-2.65, 0.42);
    p.lineTo(-2.65, 2.16);
    p.quadraticCurveTo(-2.65, 2.30, -2.51, 2.30);
    p.lineTo(1.05, 2.30);
    p.quadraticCurveTo(1.24, 2.30, 1.34, 2.18);
    p.lineTo(2.02, 1.40);
    p.quadraticCurveTo(2.40, 1.36, 2.55, 1.18);
    p.quadraticCurveTo(2.66, 1.12, 2.66, 0.95);
    p.lineTo(2.66, 0.52);
    p.quadraticCurveTo(2.66, 0.42, 2.56, 0.42);
    p.lineTo(2.14, 0.42);
    p.absarc(1.62, 0.42, 0.52, 0, Math.PI, false);
    p.lineTo(-1.0, 0.42);
    p.absarc(-1.52, 0.42, 0.52, 0, Math.PI, false);
    p.lineTo(-2.65, 0.42);

    var depth = W - 2 * BEVEL;
    var geo = new THREE.ExtrudeGeometry(p, {
      depth: depth, bevelEnabled: true, bevelThickness: BEVEL, bevelSize: BEVEL, bevelSegments: 2, curveSegments: 14
    });
    geo.rotateY(-Math.PI / 2);          // 轮廓平面 (z, y) → 车身侧面；挤出方向 → 车宽 x
    geo.translate(depth / 2, 0, 0);
    var body = add(new THREE.Mesh(geo, toon(WHITE)), 0, 0, 0);
    edges(body, 40, 0.42);

    // 轮拱内衬（深色），挡住白色拱壁
    [1.62, -1.52].forEach(function (z) {
      var liner = new THREE.Mesh(new THREE.CylinderGeometry(0.455, 0.455, W - 0.08, 22, 1, true, 0, Math.PI), toon(0x262d34));
      liner.material.side = THREE.DoubleSide;
      liner.rotation.z = Math.PI / 2;
      add(liner, 0, 0.42, z);
    });

    /* ---------- 侧面贴片工具：轮廓坐标 (z, y) 直接写，两侧镜像 ---------- */
    function sidePoly(pts, side, mat, lift) {
      var sh = new THREE.Shape();
      pts.forEach(function (q, i) {
        var u = -side * q[0];
        if (i) sh.lineTo(u, q[1]); else sh.moveTo(u, q[1]);
      });
      var m = new THREE.Mesh(new THREE.ShapeGeometry(sh), mat);
      m.rotation.y = side * Math.PI / 2;
      m.position.x = side * (HALF + (lift || 0.006));
      car.add(m);
      return m;
    }
    function roundRect(z0, y0, z1, y1, r) {
      var pts = [];
      [[z1 - r, y0 + r, -Math.PI / 2], [z1 - r, y1 - r, 0], [z0 + r, y1 - r, Math.PI / 2], [z0 + r, y0 + r, Math.PI]]
        .forEach(function (c) {
          for (var k = 0; k <= 4; k++) {
            var a = c[2] + k * Math.PI / 8;
            pts.push([c[0] + r * Math.cos(a), c[1] + r * Math.sin(a)]);
          }
        });
      return pts;
    }
    function crossPts(cz, cy, a, b) {
      return [[cz - b, cy + a], [cz + b, cy + a], [cz + b, cy + b], [cz + a, cy + b], [cz + a, cy - b], [cz + b, cy - b],
        [cz + b, cy - a], [cz - b, cy - a], [cz - b, cy - b], [cz - a, cy - b], [cz - a, cy + b], [cz - b, cy + b]];
    }
    function rect(z0, y0, z1, y1) { return [[z0, y0], [z1, y0], [z1, y1], [z0, y1]]; }

    /* ---------- 前风挡（贴着斜面） ---------- */
    (function () {
      var z1 = 1.34, y1 = 2.18, z2 = 2.02, y2 = 1.40;
      var dz = z2 - z1, dy = y2 - y1, len = Math.sqrt(dz * dz + dy * dy);
      var nz = -dy / len, ny = dz / len, lift = BEVEL + 0.008;
      var ws = new THREE.Mesh(new THREE.PlaneGeometry(1.80, len - 0.16), toon(GLASS));
      ws.rotation.x = Math.atan2(-ny, nz);
      add(ws, 0, (y1 + y2) / 2 + ny * lift, (z1 + z2) / 2 + nz * lift);
    })();

    var red = flat(RED), blue = flat(BLUE), glass = toon(GLASS), hi = flat(GLASS_HI), frost = toon(FROST),
      trim = toon(TRIM), seam = toon(SEAM);
    bothSides(function (sd) {
      sidePoly([[0.86, 1.52], [1.86, 1.52], [1.36, 2.10], [0.86, 2.10]], sd, glass);        // 驾驶室侧窗
      sidePoly([[1.00, 1.60], [1.12, 1.60], [1.30, 2.00], [1.18, 2.00]], sd, hi, 0.010);    // 车窗高光
      sidePoly(roundRect(-0.30, 1.62, 0.52, 2.06, 0.06), sd, frost);                         // 医疗舱磨砂窗
      sidePoly([[-2.60, 1.00], [2.58, 1.00], [2.46, 1.22], [-2.60, 1.22]], sd, red);         // 红色腰线
      sidePoly([[-2.60, 1.26], [2.20, 1.26], [2.16, 1.30], [-2.60, 1.30]], sd, blue);        // 蓝色细线
      sidePoly(crossPts(-1.06, 1.76, 0.28, 0.09), sd, red);                                  // 红十字
      sidePoly(rect(-0.98, 0.42, 1.08, 0.60), sd, trim);                                     // 侧裙
      sidePoly(rect(-2.62, 0.42, -2.07, 0.60), sd, trim);
      sidePoly(rect(0.745, 0.62, 0.76, 2.14), sd, seam, 0.009);                              // 驾驶室门缝
      sidePoly(rect(1.95, 0.97, 1.965, 1.46), sd, seam, 0.009);
      sidePoly(rect(0.76, 0.95, 1.965, 0.965), sd, seam, 0.009);
      sidePoly(rect(0.86, 1.36, 1.04, 1.41), sd, trim, 0.011);                               // 门把手
    });
    // 右侧（靠路沿一侧）滑门：门缝 + 把手
    [rect(-0.62, 0.62, -0.605, 2.14), rect(0.645, 0.62, 0.66, 2.14), rect(-0.62, 2.125, 0.66, 2.14),
      rect(-0.62, 0.62, 0.66, 0.635)].forEach(function (r) { sidePoly(r, -1, seam, 0.009); });
    sidePoly(rect(0.44, 1.36, 0.58, 1.41), -1, trim, 0.011);

    // 「120 急救」字样（浏览器里用画布生成贴图；没有画布的环境跳过）
    (function () {
      if (typeof document === "undefined" || !document.createElement) return;
      var c = document.createElement("canvas");
      c.width = 512; c.height = 160;
      var g = c.getContext && c.getContext("2d");
      if (!g) return;
      g.fillStyle = "#e0472f";
      g.textAlign = "center";
      g.textBaseline = "middle";
      g.font = "900 112px 'Arial Black', 'Microsoft YaHei', 'PingFang SC', sans-serif";
      g.fillText("120 急救", 256, 86);
      var tex = new THREE.CanvasTexture(c);
      tex.anisotropy = 4;
      var mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false });
      bothSides(function (sd) {
        var t = new THREE.Mesh(new THREE.PlaneGeometry(1.0, 0.3125), mat);
        t.rotation.y = sd * Math.PI / 2;
        add(t, sd * (HALF + 0.007), 1.74, -2.0);
      });
    })();

    /* ---------- 车头 ---------- */
    add(new THREE.Mesh(new THREE.PlaneGeometry(1.12, 0.30), toon(0x3d4a56)), 0, 0.77, 2.716);   // 格栅
    [0.69, 0.77, 0.85].forEach(function (y) {
      add(new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.024, 0.02), toon(0xc9d1d8)), 0, y, 2.722);
    });
    [-1, 1].forEach(function (sx) {
      add(new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.20, 0.04), toon(0x4b5866)), sx * 0.72, 0.98, 2.695);
      add(new THREE.Mesh(new THREE.BoxGeometry(0.40, 0.15, 0.06), flat(0xfff2c4)), sx * 0.72, 0.98, 2.70); // 大灯
    });
    var fBumper = add(new THREE.Mesh(new THREE.BoxGeometry(2.12, 0.24, 0.30), toon(TRIM)), 0, 0.47, 2.66);
    edges(fBumper, 30, 0.35);
    add(new THREE.Mesh(new THREE.PlaneGeometry(0.44, 0.13), flat(BLUE)), 0, 0.47, 2.812);      // 车牌

    /* ---------- 车尾 ---------- */
    [-1, 1].forEach(function (sx) {
      var rw = add(new THREE.Mesh(new THREE.PlaneGeometry(0.62, 0.44), glass), sx * 0.46, 1.80, -2.708);
      rw.rotation.y = Math.PI;
      add(new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.56, 0.04), flat(0xd93a26)), sx * 0.90, 1.02, -2.715);   // 尾灯
      add(new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.14, 0.04), flat(0xffb347)), sx * 0.90, 1.38, -2.715);
      add(new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.08, 0.04), flat(0xffb347)), sx * 0.80, 2.12, -2.715);   // 顶部示廓灯
      add(new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.16, 0.03), trim), sx * 0.10, 1.30, -2.712);            // 后门把手
    });
    add(new THREE.Mesh(new THREE.BoxGeometry(0.014, 1.66, 0.012), seam), 0, 1.30, -2.706);                    // 对开门缝
    var rBumper = add(new THREE.Mesh(new THREE.BoxGeometry(2.10, 0.22, 0.26), toon(TRIM)), 0, 0.46, -2.69);
    edges(rBumper, 30, 0.35);
    add(new THREE.Mesh(new THREE.BoxGeometry(1.30, 0.05, 0.24), toon(0x9aa7b2)), 0, 0.34, -2.86);            // 踏板

    /* ---------- 车顶：警示灯排 + 红十字 + 空调 ---------- */
    var barBase = add(new THREE.Mesh(new THREE.BoxGeometry(1.56, 0.08, 0.36), toon(0xdfe5ea)), 0, 2.39, 0.70);
    edges(barBase, 30, 0.35);
    var beaconL = add(new THREE.Mesh(new THREE.BoxGeometry(0.56, 0.15, 0.30), new THREE.MeshBasicMaterial({ color: 0xff3524 })), -0.44, 2.505, 0.70);
    var beaconR = add(new THREE.Mesh(new THREE.BoxGeometry(0.56, 0.15, 0.30), new THREE.MeshBasicMaterial({ color: 0x2f6bff })), 0.44, 2.505, 0.70);
    add(new THREE.Mesh(new THREE.BoxGeometry(0.26, 0.12, 0.28), toon(0xf4f6f8)), 0, 2.49, 0.70);
    var rc = new THREE.Shape();
    crossPts(0, 0, 0.36, 0.11).forEach(function (q, i) { if (i) rc.lineTo(q[0], q[1]); else rc.moveTo(q[0], q[1]); });
    var roofCross = add(new THREE.Mesh(new THREE.ShapeGeometry(rc), red), 0, 2.356, -0.95);
    roofCross.rotation.x = -Math.PI / 2;
    var ac = add(new THREE.Mesh(new THREE.BoxGeometry(0.86, 0.12, 0.62), toon(0xeef2f5)), 0, 2.41, -2.0);
    edges(ac, 30, 0.35);

    /* ---------- 后视镜 ---------- */
    bothSides(function (sd) {
      add(new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.04, 0.05), trim), sd * (HALF + 0.10), 1.56, 1.78);
      var head = add(new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.26, 0.17), toon(0x4b5866)), sd * (HALF + 0.22), 1.60, 1.76);
      edges(head, 30, 0.35);
    });

    /* ---------- 车轮 ---------- */
    [1.62, -1.52].forEach(function (z) {
      bothSides(function (sd) {
        var x = sd * (HALF - 0.17);
        [[0.42, 0.30, TIRE, 28], [0.25, 0.31, RIM, 20], [0.19, 0.312, RIM_IN, 18], [0.085, 0.33, HUB, 12]].forEach(function (w, i) {
          var m = add(new THREE.Mesh(new THREE.CylinderGeometry(w[0], w[0], w[1], w[3]), toon(w[2])), x, 0.42, z);
          m.rotation.z = Math.PI / 2;
          if (i === 0) edges(m, 40, 0.3);
        });
      });
    });

    car.traverse(function (o) {
      if (o.isMesh && !o.material.isMeshBasicMaterial) { o.castShadow = true; o.receiveShadow = true; }
    });
    return { group: car, beacons: [beaconL, beaconR] };
  };
})(typeof window !== "undefined" ? window : globalThis);
