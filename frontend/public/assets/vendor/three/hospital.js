/* ============================================================
   MedTriage 首页 · 阳光社区医院三维微缩场景
   Three.js r147 (UMD) + OrbitControls
   三渲二：MeshToonMaterial 阶调分离 + 轮廓线
   交互：拖拽旋转 / 滚轮缩放 / 闲置缓慢自转
   ============================================================ */
(function () {
  "use strict";

  /*
   * Vue 版：脚本只加载一次；每次进入落地页调用 __mtMountHospitalScene(canvas, wrap) 挂载一次，
   * 返回的清理函数在离开落地页时调用（停渲染循环、断开观察器、释放 WebGL 上下文）。
   * 以前脚本自己找 #sceneCanvas 且只执行一次：从登录页返回首页时新画布没人渲染，三维场景消失。
   */
  window.__mtMountHospitalScene = function (canvas, wrap) {
  if (!canvas || !wrap || typeof THREE === "undefined") return null;

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- 渲染器 ---------- */
  var renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
  } catch (e) {
    var fb = wrap.querySelector(".hero-scene-fallback");
    if (fb) fb.hidden = false;
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0); // 透明，融入网页背景
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  var scene = new THREE.Scene();

  var camera = new THREE.PerspectiveCamera(35, 1, 0.1, 200);
  camera.position.set(0, 7, 23);

  /* ---------- 控制器 ---------- */
  var controls = new THREE.OrbitControls(camera, canvas);
  controls.target.set(0, 2.4, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.07;
  controls.enablePan = false;
  controls.minDistance = 11;
  controls.maxDistance = 32;
  controls.minPolarAngle = 0.32;
  controls.maxPolarAngle = 1.42;
  controls.autoRotate = false;
  controls.autoRotateSpeed = 0.45;

  var idleTimer = null;
  var firstRotateTimer = null;
  controls.addEventListener("start", function () {
    controls.autoRotate = false;
    if (idleTimer) clearTimeout(idleTimer);
    if (firstRotateTimer) { clearTimeout(firstRotateTimer); firstRotateTimer = null; }
    wrap.classList.add("interacted");
  });
  controls.addEventListener("end", function () {
    if (reduceMotion) return;
    idleTimer = setTimeout(function () { controls.autoRotate = true; }, 4000);
  });

  // 首次展示 10 秒后开始缓慢自转（等机器人走出+站定晃牌子展示完）
  if (!reduceMotion) {
    firstRotateTimer = setTimeout(function () { controls.autoRotate = true; }, 10000);
  }

  /* ---------- 三渲二材质工具 ---------- */
  var gradientMap = (function () {
    var data = new Uint8Array([150, 200, 235, 255]); // 4 阶调（提亮暗部，保持开朗）
    var tex = new THREE.DataTexture(data, 4, 1, THREE.RedFormat);
    tex.minFilter = THREE.NearestFilter;
    tex.magFilter = THREE.NearestFilter;
    tex.needsUpdate = true;
    return tex;
  })();

  function toon(color) {
    return new THREE.MeshToonMaterial({ color: color, gradientMap: gradientMap });
  }
  function flat(color) { // 不受光的平面元素（地贴、水面等）
    return new THREE.MeshBasicMaterial({ color: color });
  }

  var EDGE_COLOR = 0x3a5568;
  function edges(mesh, threshold, opacity) {
    var geo = new THREE.EdgesGeometry(mesh.geometry, threshold || 30);
    var line = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({
      color: EDGE_COLOR, transparent: true, opacity: opacity == null ? 0.5 : opacity
    }));
    mesh.add(line);
    return line;
  }

  function box(w, h, d, color, withEdges) {
    var m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), toon(color));
    if (withEdges !== false) edges(m);
    m.castShadow = true;
    m.receiveShadow = true;
    return m;
  }
  function cyl(rt, rb, h, color, seg, withEdges) {
    var m = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg || 20), toon(color));
    if (withEdges) edges(m);
    m.castShadow = true;
    m.receiveShadow = true;
    return m;
  }
  function ball(r, color, seg) {
    var m = new THREE.Mesh(new THREE.SphereGeometry(r, seg || 18, (seg || 18) - 4), toon(color));
    m.castShadow = true;
    return m;
  }
  function put(parent, mesh, x, y, z, ry) {
    mesh.position.set(x, y, z);
    if (ry) mesh.rotation.y = ry;
    parent.add(mesh);
    return mesh;
  }

  /* ---------- 灯光（晴朗白天） ---------- */
  scene.add(new THREE.HemisphereLight(0xd4e9f8, 0xf0e6d2, 0.98));
  var sun = new THREE.DirectionalLight(0xfff1d8, 1.12);
  sun.position.set(11, 17, 9);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.camera.left = -16; sun.shadow.camera.right = 16;
  sun.shadow.camera.top = 16; sun.shadow.camera.bottom = -16;
  sun.shadow.camera.near = 2; sun.shadow.camera.far = 46;
  sun.shadow.bias = -0.002;
  scene.add(sun);

  /* ---------- 天空中可见的太阳 ---------- */
  var sunBall = new THREE.Mesh(
    new THREE.SphereGeometry(1.6, 24, 18),
    new THREE.MeshBasicMaterial({ color: 0xfff5e0, transparent: true, opacity: 0.92 })
  );
  sunBall.position.set(16, 18, -16);
  scene.add(sunBall);
  // 太阳光晕（两层半透明球）
  var halo1 = new THREE.Mesh(
    new THREE.SphereGeometry(2.6, 20, 16),
    new THREE.MeshBasicMaterial({ color: 0xffeed0, transparent: true, opacity: 0.22, depthWrite: false })
  );
  halo1.position.copy(sunBall.position); scene.add(halo1);
  var halo2 = new THREE.Mesh(
    new THREE.SphereGeometry(4.2, 20, 16),
    new THREE.MeshBasicMaterial({ color: 0xffe8c0, transparent: true, opacity: 0.1, depthWrite: false })
  );
  halo2.position.copy(sunBall.position); scene.add(halo2);

  var world = new THREE.Group(); // 整座微缩模型
  scene.add(world);

  /* ============================================================
     底座：圆角方盘 + 顶面分区（草坪 / 广场 / 道路）
     ============================================================ */
  (function buildBase() {
    // 圆角矩形轮廓
    var s = 11.4, r = 0.9;
    var shape = new THREE.Shape();
    shape.moveTo(-s + r, -s);
    shape.lineTo(s - r, -s); shape.absarc(s - r, -s + r, r, -Math.PI / 2, 0);
    shape.lineTo(s, s - r); shape.absarc(s - r, s - r, r, 0, Math.PI / 2);
    shape.lineTo(-s + r, s); shape.absarc(-s + r, s - r, r, Math.PI / 2, Math.PI);
    shape.lineTo(-s, -s + r); shape.absarc(-s + r, -s + r, r, Math.PI, Math.PI * 1.5);
    var geo = new THREE.ExtrudeGeometry(shape, {
      depth: 1, bevelEnabled: true, bevelThickness: 0.16, bevelSize: 0.16, bevelSegments: 2, curveSegments: 10
    });
    geo.rotateX(-Math.PI / 2);
    var base = new THREE.Mesh(geo, toon(0xf3ecdd)); // 奶白底座
    base.position.y = -1.16;
    base.receiveShadow = true;
    edges(base, 40, 0.4);
    world.add(base);

    // 顶面地铺：草坪（整体浅绿）
    var lawn = new THREE.Mesh(new THREE.PlaneGeometry(22.4, 22.4), toon(0x9ed291));
    lawn.rotation.x = -Math.PI / 2;
    lawn.position.y = 0.001;
    lawn.receiveShadow = true;
    world.add(lawn);

    // 门前广场铺装（楼前区域）
    var plaza = new THREE.Mesh(new THREE.PlaneGeometry(15, 9.6), toon(0xe9e9e4));
    plaza.rotation.x = -Math.PI / 2;
    plaza.position.set(0, 0.012, 5.6);
    plaza.receiveShadow = true;
    world.add(plaza);

    // 广场砖缝细线
    for (var i = -2; i <= 2; i++) {
      var seam = new THREE.Mesh(new THREE.PlaneGeometry(15, 0.04), flat(0xdedfd8));
      seam.rotation.x = -Math.PI / 2;
      seam.position.set(0, 0.02, 5.6 + i * 1.9);
      world.add(seam);
    }
    // 广场中央同心圆铺装（微缩模型感）
    for (var ri = 1; ri <= 3; ri++) {
      var ringMesh = new THREE.Mesh(new THREE.RingGeometry(ri * 1.05, ri * 1.05 + 0.07, 40), flat(0xdde2da));
      ringMesh.rotation.x = -Math.PI / 2;
      ringMesh.position.set(0.5, 0.018, 6.6);
      world.add(ringMesh);
    }

    // 左侧车道 + 两个停车位
    var road = new THREE.Mesh(new THREE.PlaneGeometry(5.4, 9.6), toon(0xcfd6dc));
    road.rotation.x = -Math.PI / 2;
    road.position.set(-8.3, 0.012, 5.6);
    road.receiveShadow = true;
    world.add(road);
    for (var p = 0; p < 2; p++) { // 车位白线
      var z0 = 3.4 + p * 4.2;
      var lineL = new THREE.Mesh(new THREE.PlaneGeometry(0.12, 3.4), flat(0xffffff));
      lineL.rotation.x = -Math.PI / 2; lineL.position.set(-10.2, 0.024, z0 + 1.7); world.add(lineL);
      var lineR = lineL.clone(); lineR.position.x = -6.4; world.add(lineR);
      var lineB = new THREE.Mesh(new THREE.PlaneGeometry(3.9, 0.12), flat(0xffffff));
      lineB.rotation.x = -Math.PI / 2; lineB.position.set(-8.3, 0.024, z0 + 3.4); world.add(lineB);
    }
    // 车位地标十字（急救车位）
    var crossV = new THREE.Mesh(new THREE.PlaneGeometry(0.34, 1.5), flat(0xe0472f));
    crossV.rotation.x = -Math.PI / 2; crossV.position.set(-8.3, 0.028, 4.9); world.add(crossV);
    var crossH = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 0.34), flat(0xe0472f));
    crossH.rotation.x = -Math.PI / 2; crossH.position.set(-8.3, 0.028, 4.9); world.add(crossH);
  })();

  /* ============================================================
     门诊楼主体
     ============================================================ */
  var glassMat = new THREE.MeshPhongMaterial({
    color: 0xa8dcf2, transparent: true, opacity: 0.42,
    shininess: 120, specular: 0xeffaff, side: THREE.DoubleSide, depthWrite: false
  });

  var doorL, doorR, signMesh;
  (function buildHospital() {
    var bld = new THREE.Group();
    bld.position.set(0, 0, -2.5);
    world.add(bld);

    var WALL = 0xf9f4e8;      // 暖米白墙体
    var TRIM = 0x8fc3de;      // 浅蓝檐口
    var GLASSBAND = 0x64b8e8; // 二层窗带

    // —— 一层：玻璃大厅 + 两端实墙 ——
    // 内部地板（大厅）
    var floor = new THREE.Mesh(new THREE.PlaneGeometry(12.6, 6.6), toon(0xf2ede2));
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(0, 0.03, 0);
    floor.receiveShadow = true;
    bld.add(floor);

    // 一层侧墙与后墙
    put(bld, box(0.5, 3.2, 7, WALL), -6.25, 1.6, 0);
    put(bld, box(0.5, 3.2, 7, WALL), 6.25, 1.6, 0);
    put(bld, box(13, 3.2, 0.5, WALL), 0, 1.6, -3.25);
    // 一层正面上沿（玻璃幕墙顶梁）
    put(bld, box(13, 0.5, 0.5, WALL), 0, 2.95, 3.25);
    // 正面两端墙柱
    put(bld, box(2.2, 3.2, 0.5, WALL), -5.4, 1.6, 3.25);
    put(bld, box(2.2, 3.2, 0.5, WALL), 5.4, 1.6, 3.25);
    // 门洞两侧小柱
    put(bld, box(0.4, 3.2, 0.5, WALL), -2.0, 1.6, 3.25);
    put(bld, box(0.4, 3.2, 0.5, WALL), 2.0, 1.6, 3.25);

    // 一层正面玻璃幕墙（左 / 右两片，中间留门洞）
    var glassL = new THREE.Mesh(new THREE.PlaneGeometry(2.2, 2.7), glassMat);
    glassL.position.set(-3.1, 1.5, 3.26); bld.add(glassL);
    var glassR = glassL.clone(); glassR.position.x = 3.1; bld.add(glassR);
    // 玻璃竖梃
    [-4.2, -3.1, 3.1, 4.2].forEach(function (x) {
      var mullion = new THREE.Mesh(new THREE.BoxGeometry(0.08, 2.7, 0.08), toon(0xffffff));
      mullion.position.set(x, 1.5, 3.28);
      bld.add(mullion);
    });

    // —— 自动玻璃门（两扇，可滑动） ——
    var doorMat = new THREE.MeshPhongMaterial({
      color: 0xcdeefb, transparent: true, opacity: 0.45,
      shininess: 140, specular: 0xffffff, side: THREE.DoubleSide, depthWrite: false
    });
    var doorFrame = new THREE.MeshPhongMaterial({ color: 0xdfe9ee });
    function makeDoor(handleSide) { // handleSide: 1 把手在右，-1 把手在左
      var g = new THREE.Group();
      var pane = new THREE.Mesh(new THREE.PlaneGeometry(1.55, 2.5), doorMat);
      pane.position.y = 1.3;
      g.add(pane);
      var rail = new THREE.Mesh(new THREE.BoxGeometry(1.55, 0.14, 0.06), doorFrame);
      rail.position.y = 0.12; g.add(rail);
      var rail2 = rail.clone(); rail2.position.y = 2.5; g.add(rail2);
      var handle = new THREE.Mesh(new THREE.BoxGeometry(0.06, 1.1, 0.06), doorFrame);
      handle.position.set(0.62 * handleSide, 1.3, 0.03); g.add(handle);
      return g;
    }
    doorL = makeDoor(1); doorL.position.set(-0.79, 0, 3.3); bld.add(doorL);
    doorR = makeDoor(-1); doorR.position.set(0.79, 0, 3.3); bld.add(doorR);
    // 门洞上方「门诊」灯箱
    signMesh = (function () {
      var cv = document.createElement("canvas"); cv.width = 512; cv.height = 128;
      var ctx = cv.getContext("2d");
      ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, 512, 128);
      ctx.fillStyle = "#1387c0";
      ctx.font = "600 64px 'Noto Sans SC', sans-serif";
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText("门 诊 大 厅", 256, 66);
      var tex = new THREE.CanvasTexture(cv);
      var g = new THREE.Group();
      var board = new THREE.Mesh(new THREE.BoxGeometry(3.4, 0.85, 0.16),
        new THREE.MeshBasicMaterial({ map: tex }));
      g.add(board);
      edges(board, 20, 0.35);
      return g;
    })();
    signMesh.position.set(0, 2.62, 3.42);
    bld.add(signMesh);

    // —— 二层 ——
    put(bld, box(13, 3, 7, WALL), 0, 4.7, 0);
    // 二层正面横向窗带（玻璃条 + 白色竖梃）
    var band = new THREE.Mesh(new THREE.BoxGeometry(11.6, 1.5, 0.14), toon(GLASSBAND));
    band.position.set(0, 4.85, 3.53);
    bld.add(band);
    for (var i = -5; i <= 5; i++) {
      var fin = new THREE.Mesh(new THREE.BoxGeometry(0.12, 1.5, 0.2), toon(0xffffff));
      fin.position.set(i * 1.05, 4.85, 3.55);
      bld.add(fin);
    }
    // 二层侧面小窗
    [-6.32, 6.32].forEach(function (x) {
      for (var k = -1; k <= 1; k++) {
        var win = new THREE.Mesh(new THREE.BoxGeometry(0.1, 1.2, 1.4), toon(GLASSBAND));
        win.position.set(x, 4.8, k * 2);
        bld.add(win);
      }
    });

    // —— 檐口与楼顶 ——
    put(bld, box(13.7, 0.28, 7.7, TRIM), 0, 3.34, 0);          // 一层腰线
    put(bld, box(13.7, 0.34, 7.7, TRIM), 0, 6.36, 0);          // 顶部挑檐
    put(bld, box(13.2, 0.5, 7.2, WALL), 0, 6.75, 0);           // 女儿墙
    // 楼顶设备：空调外机 × 2 + 水箱
    put(bld, box(1.1, 0.7, 0.8, 0xd9dee2), -4.4, 7.15, -1.6);
    put(bld, box(1.1, 0.7, 0.8, 0xd9dee2), -3.1, 7.15, -1.6);
    put(bld, cyl(0.65, 0.65, 0.9, 0xe8eef2, 18, true), 4.6, 7.25, -1.8);

    // —— 楼顶红十字标志 ——
    var crossG = new THREE.Group();
    var RED = 0xe0472f;
    var cBase = box(1.7, 1.7, 0.5, 0xffffff); cBase.position.y = 0.85; crossG.add(cBase);
    var cv1 = box(0.42, 1.24, 0.54, RED); cv1.position.y = 0.85; crossG.add(cv1);
    var ch1 = box(1.24, 0.42, 0.54, RED); ch1.position.y = 0.85; crossG.add(ch1);
    crossG.position.set(0, 6.9, 2.4);
    bld.add(crossG);

    // —— 入口雨棚 ——
    var canopy = box(8.2, 0.22, 2.9, 0xffffff);
    canopy.position.set(0, 3.28, 4.4);
    bld.add(canopy);
    var canopyEdge = box(8.2, 0.26, 0.14, 0xe8f2f8); // 雨棚压边（浅色）
    canopyEdge.position.set(0, 3.26, 5.84);
    bld.add(canopyEdge);
    [-3.7, 3.7].forEach(function (x) {
      var col = cyl(0.09, 0.09, 3.2, 0xe8eef2, 12, true);
      col.position.set(x, 1.6, 5.4);
      bld.add(col);
    });

    // 入口台阶（两级，宽于门洞）
    put(bld, box(5.2, 0.14, 1.1, 0xe2e5e1), 0, 0.07, 4.15);
    put(bld, box(4.6, 0.14, 0.7, 0xd8dcd8), 0, 0.21, 3.9);

    world.userData.building = bld;
  })();

  /* ============================================================
     大厅内部（透过玻璃可见）
     ============================================================ */
  (function buildInterior() {
    var hall = new THREE.Group();
    hall.position.set(0, 0, -2.5);
    world.add(hall);

    // —— 导医台（半圆弧形） ——
    var desk = new THREE.Mesh(
      new THREE.CylinderGeometry(1.15, 1.15, 1.05, 24, 1, false, 0, Math.PI),
      toon(0xffffff)
    );
    desk.position.set(0, 0.53, -1.2);
    desk.rotation.y = Math.PI; // 弧面朝门
    desk.castShadow = true;
    edges(desk, 40, 0.35);
    hall.add(desk);
    var deskTop = cyl(1.25, 1.25, 0.08, 0x8fc3de, 24);
    deskTop.position.set(0, 1.08, -1.2);
    hall.add(deskTop);
    // 台上小绿植
    var potP = cyl(0.12, 0.09, 0.16, 0xe0a568, 10);
    potP.position.set(0.5, 1.2, -1.5); hall.add(potP);
    var leafP = ball(0.16, 0x68b56e, 10);
    leafP.position.set(0.5, 1.38, -1.5); hall.add(leafP);

    // —— 候诊椅（两排连排座椅，浅蓝） ——
    function chairRow(x, z) {
      var row = new THREE.Group();
      for (var i = 0; i < 4; i++) {
        var seat = box(0.62, 0.1, 0.6, 0x9fcfec, false);
        seat.position.set(i * 0.72, 0.45, 0);
        row.add(seat);
        var back = box(0.62, 0.62, 0.1, 0x9fcfec, false);
        back.position.set(i * 0.72, 0.82, -0.26);
        row.add(back);
      }
      // 椅腿横梁
      var beam = box(2.7, 0.08, 0.08, 0x8a97a1, false);
      beam.position.set(1.08, 0.36, 0); row.add(beam);
      [-0.1, 2.26].forEach(function (lx) {
        var leg = box(0.08, 0.4, 0.5, 0x8a97a1, false);
        leg.position.set(lx, 0.2, 0); row.add(leg);
      });
      row.position.set(x, 0, z);
      return row;
    }
    hall.add(chairRow(-4.6, -0.6));
    hall.add(chairRow(-4.6, -2.4));

    // —— 挂号收费窗口（右侧内墙） ——
    var counter = box(0.5, 1.1, 3.2, 0xffffff);
    counter.position.set(5.5, 0.55, -1.4);
    hall.add(counter);
    var winGlass = new THREE.Mesh(new THREE.PlaneGeometry(2.8, 1.2), glassMat);
    winGlass.rotation.y = -Math.PI / 2;
    winGlass.position.set(5.6, 1.9, -1.4);
    hall.add(winGlass);
    var winSignCv = document.createElement("canvas"); winSignCv.width = 256; winSignCv.height = 64;
    var wctx = winSignCv.getContext("2d");
    wctx.fillStyle = "#1387c0"; wctx.fillRect(0, 0, 256, 64);
    wctx.fillStyle = "#ffffff"; wctx.font = "600 30px 'Noto Sans SC', sans-serif";
    wctx.textAlign = "center"; wctx.textBaseline = "middle";
    wctx.fillText("挂号 · 收费", 128, 34);
    var winSign = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.42, 1.7),
      new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(winSignCv) }));
    winSign.position.set(5.68, 2.72, -1.4);
    hall.add(winSign);

    // —— 叫号屏（后墙，发光） ——
    var screenCv = document.createElement("canvas"); screenCv.width = 512; screenCv.height = 288;
    var sctx = screenCv.getContext("2d");
    sctx.fillStyle = "#12333f"; sctx.fillRect(0, 0, 512, 288);
    sctx.fillStyle = "#7fe0a8"; sctx.font = "600 44px 'Noto Sans SC', sans-serif";
    sctx.textAlign = "center";
    sctx.fillText("请 A023 到 3 诊室", 256, 96);
    sctx.fillStyle = "#ffd98a"; sctx.font = "500 32px 'Noto Sans SC', sans-serif";
    sctx.fillText("A024 · A025 候诊中", 256, 168);
    sctx.fillStyle = "#9fd4ee"; sctx.font = "400 24px 'Noto Sans SC', sans-serif";
    sctx.fillText("请留意叫号  过号顺延", 256, 232);
    var screen = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 1.45),
      new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(screenCv) }));
    screen.position.set(1.8, 2.05, -2.9);
    hall.add(screen);
    var screenFrame = box(2.8, 1.65, 0.08, 0x2b3a44);
    screenFrame.position.set(1.8, 2.05, -2.95);
    hall.add(screenFrame);

    // —— 墙面健康宣传海报 ——
    function poster(color, label) {
      var cv = document.createElement("canvas"); cv.width = 96; cv.height = 128;
      var c2 = cv.getContext("2d");
      c2.fillStyle = "#ffffff"; c2.fillRect(0, 0, 96, 128);
      c2.fillStyle = color; c2.fillRect(8, 8, 80, 56);
      c2.fillStyle = "#33475a"; c2.font = "600 17px 'Noto Sans SC', sans-serif";
      c2.textAlign = "center"; c2.fillText(label, 48, 84);
      c2.fillStyle = "#8aa0b2"; c2.fillRect(16, 96, 64, 5); c2.fillRect(16, 106, 48, 5);
      return new THREE.Mesh(new THREE.PlaneGeometry(0.62, 0.85),
        new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(cv) }));
    }
    var p1 = poster("#8fc3de", "护眼知识"); p1.position.set(-3.2, 1.9, -2.94); hall.add(p1);
    var p2 = poster("#f4a259", "健康饮食"); p2.position.set(-4.1, 1.9, -2.94); hall.add(p2);

    // —— 室内顶灯（发光板） ——
    [-2.4, 2.4].forEach(function (x) {
      var lamp = new THREE.Mesh(new THREE.BoxGeometry(1.9, 0.06, 0.7),
        new THREE.MeshBasicMaterial({ color: 0xfff6e2 }));
      lamp.position.set(x, 2.96, -0.8);
      hall.add(lamp);
    });

    // —— 地面导视（门口 → 导医台 蓝线 + 圆点） ——
    var guide = new THREE.Mesh(new THREE.PlaneGeometry(0.22, 2.6), flat(0x63b3dd));
    guide.rotation.x = -Math.PI / 2;
    guide.position.set(0, 0.045, 1.4);
    hall.add(guide);
    var dot = new THREE.Mesh(new THREE.CircleGeometry(0.22, 16), flat(0x63b3dd));
    dot.rotation.x = -Math.PI / 2;
    dot.position.set(0, 0.045, 0);
    hall.add(dot);

    // —— 门口内侧盆栽 × 2 ——
    [-2.6, 2.6].forEach(function (x) {
      var pot = cyl(0.22, 0.17, 0.3, 0xe0a568, 12);
      pot.position.set(x, 0.15, 2.2); hall.add(pot);
      var bush = ball(0.3, 0x7cc47f, 12);
      bush.position.set(x, 0.55, 2.2); hall.add(bush);
    });

    // 大厅内暖光（让玻璃内透出温暖感）
    var warm = new THREE.PointLight(0xffe8c4, 1.0, 10);
    warm.position.set(0, 2.4, 0.5);
    hall.add(warm);
  })();

  /* ============================================================
     无障碍坡道（入口右侧）
     ============================================================ */
  (function buildRamp() {
    var ramp = new THREE.Group();
    var geo = new THREE.BoxGeometry(1.5, 0.14, 3.4);
    var slope = new THREE.Mesh(geo, toon(0xe2e5e1));
    slope.rotation.x = -0.12;
    slope.position.set(0, 0.16, 0);
    slope.castShadow = true; slope.receiveShadow = true;
    edges(slope, 30, 0.4);
    ramp.add(slope);
    // 不锈钢扶手
    [-0.62, 0.62].forEach(function (x) {
      var rail = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 3.3, 8), toon(0xb9c4cc));
      rail.rotation.x = Math.PI / 2 - 0.12;
      rail.position.set(x, 0.85, 0);
      ramp.add(rail);
      [-1.3, 0, 1.3].forEach(function (z) {
        var post = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.8, 8), toon(0xb9c4cc));
        post.position.set(x, 0.45, z);
        ramp.add(post);
      });
    });
    ramp.position.set(3.4, 0, 5.4);
    world.add(ramp);
  })();

  /* ============================================================
     救护车（急救车位）
     ============================================================ */
  var beaconL = null, beaconR = null;
  (function buildAmbulance() {
    // 模型在 ambulance.js（高顶厢式急救车）：车身轮廓挤出 + 斜风挡 + 轮拱 + 腰线 + 红十字 + 警示灯排
    if (typeof window.MTBuildAmbulance !== "function") return;
    var built = window.MTBuildAmbulance(THREE, { toon: toon, flat: flat, edges: edges });
    var car = built.group;
    beaconL = built.beacons[0];
    beaconR = built.beacons[1];
    car.scale.setScalar(0.92);
    car.position.set(-8.3, 0, 5.1);
    car.rotation.y = Math.PI / 2; // 车头朝车道前方
    world.add(car);
  })();

  /* ============================================================
     绿化：卡通树 + 花坛 + 景观水池
     ============================================================ */
  var crowns = []; // 树冠（摆动动画）
  function makeTree(x, z, scale, tint) {
    var g = new THREE.Group();
    var trunk = cyl(0.14 * scale, 0.2 * scale, 1.1 * scale, 0x8a6b52, 10);
    trunk.position.y = 0.55 * scale;
    g.add(trunk);
    var crown = new THREE.Group();
    var c1 = ball(0.85 * scale, tint || 0x7cc47f, 16); c1.position.y = 1.5 * scale; crown.add(c1);
    var c2 = ball(0.6 * scale, 0x68b56e, 14); c2.position.set(0.5 * scale, 1.15 * scale, 0.25 * scale); crown.add(c2);
    var c3 = ball(0.55 * scale, 0x8fd08d, 14); c3.position.set(-0.45 * scale, 1.2 * scale, -0.2 * scale); crown.add(c3);
    crown.userData.phase = Math.random() * Math.PI * 2;
    g.add(crown);
    crowns.push(crown);
    g.position.set(x, 0, z);
    world.add(g);
    return g;
  }
  makeTree(-9.2, -7.6, 1.15);
  makeTree(0.6, -8.6, 1.0, 0x86c984);
  makeTree(8.6, -7.8, 1.2);
  makeTree(9.6, 1.6, 0.9, 0x86c984);
  makeTree(-3.6, 9.6, 1.0);

  function makeFlowerBed(x, z, w, d) {
    var bed = new THREE.Group();
    var rim = box(w, 0.28, d, 0xd9c9a8);
    rim.position.y = 0.14; bed.add(rim);
    var soil = new THREE.Mesh(new THREE.PlaneGeometry(w - 0.24, d - 0.24), toon(0x8a6b52));
    soil.rotation.x = -Math.PI / 2; soil.position.y = 0.29; bed.add(soil);
    // 花：彩色小球点
    var colors = [0xf26d4d, 0xf5a623, 0xffffff, 0xe86a92];
    var n = Math.floor(w * d * 1.1);
    for (var i = 0; i < n; i++) {
      var f = ball(0.09, colors[i % colors.length], 8);
      f.position.set((Math.random() - 0.5) * (w - 0.5), 0.36, (Math.random() - 0.5) * (d - 0.5));
      f.castShadow = false;
      bed.add(f);
      var stem = cyl(0.02, 0.02, 0.14, 0x5d9c5f, 6);
      stem.position.copy(f.position); stem.position.y = 0.3; stem.castShadow = false;
      bed.add(stem);
    }
    bed.position.set(x, 0, z);
    world.add(bed);
  }
  makeFlowerBed(8.9, -2.2, 3.4, 2.0);
  makeFlowerBed(-9.0, -1.6, 2.6, 1.8);
  makeFlowerBed(2.4, -8.9, 3.0, 1.6);

  // —— 景观水池 + 涟漪 ——
  var ripples = [];
  (function buildPond() {
    var pond = new THREE.Group();
    var wall = cyl(1.85, 1.95, 0.4, 0xe6e1d4, 26, true);
    wall.position.y = 0.2; pond.add(wall);
    var water = new THREE.Mesh(new THREE.CircleGeometry(1.62, 26),
      new THREE.MeshPhongMaterial({ color: 0x63bfe8, transparent: true, opacity: 0.68, shininess: 160 }));
    water.rotation.x = -Math.PI / 2; water.position.y = 0.36;
    pond.add(water);
    // 涟漪圆环
    for (var i = 0; i < 2; i++) {
      var ring = new THREE.Mesh(new THREE.RingGeometry(0.5, 0.62, 26),
        new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.6, side: THREE.DoubleSide }));
      ring.rotation.x = -Math.PI / 2; ring.position.y = 0.38;
      ring.userData.phase = i * 0.5;
      pond.add(ring);
      ripples.push(ring);
    }
    pond.position.set(6.6, 0, 7.4);
    world.add(pond);
  })();

  /* ============================================================
     街道家具：长椅 / 路灯 / 导诊牌 / 自行车棚
     ============================================================ */
  (function buildFurniture() {
    // —— 长椅 × 2 ——
    function bench(x, z, ry) {
      var g = new THREE.Group();
      var seat = box(1.7, 0.09, 0.5, 0xc89b6d);
      seat.position.y = 0.46; g.add(seat);
      var back = box(1.7, 0.44, 0.09, 0xc89b6d);
      back.position.set(0, 0.82, -0.22); g.add(back);
      [-0.7, 0.7].forEach(function (lx) {
        var leg = box(0.09, 0.44, 0.44, 0x6b7a86, false);
        leg.position.set(lx, 0.22, 0); g.add(leg);
      });
      g.position.set(x, 0, z); g.rotation.y = ry;
      world.add(g);
    }
    bench(4.4, 8.9, Math.PI);
    bench(-1.6, 9.4, Math.PI);

    // —— 路灯 × 2 ——
    function lamp(x, z) {
      var g = new THREE.Group();
      var pole = cyl(0.06, 0.09, 3.4, 0x7a8a96, 10);
      pole.position.y = 1.7; g.add(pole);
      var arm = box(0.08, 0.08, 0.9, 0x7a8a86, false);
      arm.position.set(0, 3.42, 0.4); g.add(arm);
      var head = new THREE.Mesh(new THREE.SphereGeometry(0.2, 12, 10),
        new THREE.MeshBasicMaterial({ color: 0xfff3cf }));
      head.position.set(0, 3.34, 0.82); g.add(head);
      g.position.set(x, 0, z);
      world.add(g);
    }
    lamp(10.2, 5.4);
    lamp(-10.0, -4.6);

    // —— 导诊牌（入口左侧） ——
    var sign = new THREE.Group();
    var spole = cyl(0.06, 0.06, 2.0, 0x8a97a1, 8);
    spole.position.y = 1.0; sign.add(spole);
    var cv = document.createElement("canvas"); cv.width = 256; cv.height = 160;
    var c2 = cv.getContext("2d");
    c2.fillStyle = "#1387c0"; c2.fillRect(0, 0, 256, 160);
    c2.fillStyle = "#ffffff";
    c2.font = "600 34px 'Noto Sans SC', sans-serif"; c2.textAlign = "left";
    c2.fillText("门诊 →", 26, 52);
    c2.fillText("急诊 ↑", 26, 100);
    c2.font = "400 22px 'Noto Sans SC', sans-serif"; c2.fillStyle = "#cfe9f7";
    c2.fillText("停车场 P ←", 26, 142);
    var board = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.95, 0.08),
      new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(cv) }));
    board.position.y = 2.15; sign.add(board);
    edges(board, 20, 0.4);
    sign.position.set(-3.6, 0, 6.2);
    sign.rotation.y = 0.3;
    world.add(sign);

    // —— 自行车棚 + 三辆小车 ——
    var shed = new THREE.Group();
    var roof = box(3.6, 0.1, 1.9, 0x9fc4d8);
    roof.position.y = 1.7; roof.rotation.z = 0.06; shed.add(roof);
    [[-1.6, -0.8], [1.6, -0.8], [-1.6, 0.8], [1.6, 0.8]].forEach(function (p) {
      var leg = cyl(0.05, 0.05, 1.7, 0x8a97a1, 8);
      leg.position.set(p[0], 0.85, p[1]); shed.add(leg);
    });
    function bike(x, color) {
      var b = new THREE.Group();
      var w1 = new THREE.Mesh(new THREE.TorusGeometry(0.26, 0.05, 8, 18), toon(0x3a444e));
      w1.position.set(-0.34, 0.26, 0); b.add(w1);
      var w2 = w1.clone(); w2.position.x = 0.34; b.add(w2);
      var frame = box(0.62, 0.07, 0.07, color, false);
      frame.position.y = 0.44; frame.rotation.z = 0.12; b.add(frame);
      var bar = box(0.07, 0.34, 0.07, color, false);
      bar.position.set(0.3, 0.62, 0); b.add(bar);
      var seat = box(0.2, 0.06, 0.14, 0x3a444e, false);
      seat.position.set(-0.18, 0.62, 0); b.add(seat);
      b.position.set(x, 0, 0);
      return b;
    }
    shed.add(bike(-1.0, 0xe86a92));
    shed.add(bike(0.1, 0x63b3dd));
    shed.add(bike(1.1, 0xf5a623));
    shed.position.set(-8.2, 0, -8.0);
    world.add(shed);
  })();

  /* ============================================================
     漂浮的白云（三渲二球组）
     ============================================================ */
  var clouds = [];
  (function buildClouds() {
    function cloud(y, speed, scale) {
      var g = new THREE.Group();
      var mat = toon(0xffffff);
      [[0, 0, 0, 0.9], [0.85, -0.12, 0.2, 0.62], [-0.8, -0.1, -0.15, 0.58], [0.3, 0.28, -0.2, 0.5]].forEach(function (p) {
        var s = new THREE.Mesh(new THREE.SphereGeometry(p[3] * scale, 14, 10), mat);
        s.position.set(p[0] * scale, p[1] * scale, p[2] * scale);
        s.castShadow = false;
        g.add(s);
      });
      g.scale.y = 0.72;
      g.position.set(-30, y, -6 - Math.random() * 6);
      g.userData.speed = speed;
      world.add(g);
      clouds.push(g);
    }
    cloud(10.5, 0.5, 1.2);
    cloud(12.2, 0.34, 0.9);
    cloud(9.2, 0.62, 0.7);
  })();

  /* ---------- 地面光斑（树影流光，缓慢漂移） ---------- */
  (function buildLightSpots() {
    var cv = document.createElement("canvas"); cv.width = cv.height = 256;
    var ctx = cv.getContext("2d");
    for (var i = 0; i < 26; i++) {
      var x = Math.random() * 256, y = Math.random() * 256, r = 8 + Math.random() * 22;
      var grad = ctx.createRadialGradient(x, y, 0, x, y, r);
      grad.addColorStop(0, "rgba(255,244,200,0.55)");
      grad.addColorStop(1, "rgba(255,244,200,0)");
      ctx.fillStyle = grad;
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
    }
    var tex = new THREE.CanvasTexture(cv);
    var spots = new THREE.Mesh(new THREE.PlaneGeometry(11, 8),
      new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.5, depthWrite: false }));
    spots.rotation.x = -Math.PI / 2;
    spots.position.set(2.5, 0.04, 6);
    world.add(spots);
    world.userData.spots = spots;
  })();

  /* ============================================================
     小机器人：从门里走出，举着欢迎牌
     ============================================================ */
  var robot = (function () {
    var g = new THREE.Group();
    // 机器人专属阶调：暗部更暗，白身上也能读出体积（解决太白、反光看不清）
    var robotGrad = (function () {
      var data = new Uint8Array([85, 150, 215, 255]);
      var tex = new THREE.DataTexture(data, 4, 1, THREE.RedFormat);
      tex.minFilter = THREE.NearestFilter;
      tex.magFilter = THREE.NearestFilter;
      tex.needsUpdate = true;
      return tex;
    })();
    var bodyMat = new THREE.MeshToonMaterial({ color: 0xd6e2ec, gradientMap: robotGrad });
    var accentMat = new THREE.MeshToonMaterial({ color: 0x1387c0, gradientMap: gradientMap });
    var darkMat = new THREE.MeshToonMaterial({ color: 0x2a3f52, gradientMap: gradientMap });
    var eyeMat = new THREE.MeshBasicMaterial({ color: 0x22aaff });
    var cheekMat = new THREE.MeshBasicMaterial({ color: 0xffb6c1, transparent: true, opacity: 0.7 });

    // 大头（占身体比例大，Q版感）
    var head = new THREE.Mesh(new THREE.SphereGeometry(0.42, 24, 18), bodyMat);
    head.position.y = 0.95;
    head.castShadow = true; head.receiveShadow = true;
    g.add(head);

    // 大眼睛（两个发光蓝色椭圆）
    var eyeGeo = new THREE.SphereGeometry(0.075, 12, 10);
    eyeGeo.scale(1, 1.3, 0.6);
    var eyeL = new THREE.Mesh(eyeGeo, eyeMat);
    eyeL.position.set(-0.14, 0.98, 0.38); g.add(eyeL);
    var eyeR = eyeL.clone(); eyeR.position.x = 0.14; g.add(eyeR);

    // 腮红（两个粉色小球贴在脸上）
    var cheekL = new THREE.Mesh(new THREE.SphereGeometry(0.05, 8, 8), cheekMat);
    cheekL.position.set(-0.24, 0.88, 0.34); g.add(cheekL);
    var cheekR = cheekL.clone(); cheekR.position.x = 0.24; g.add(cheekR);

    // 头顶小天线 + 发光球
    var ant = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.025, 0.2, 8), darkMat);
    ant.position.y = 1.4; g.add(ant);
    var antBall = new THREE.Mesh(new THREE.SphereGeometry(0.055, 12, 10), eyeMat);
    antBall.position.y = 1.52; g.add(antBall);

    // 身体（圆胖胶囊，比头小）
    var body = new THREE.Mesh(new THREE.CapsuleGeometry(0.3, 0.32, 8, 16), bodyMat);
    body.position.y = 0.32;
    body.castShadow = true; body.receiveShadow = true; // 头部会在身上投出阴影
    g.add(body);

    // 胸前蓝色十字装饰（呼应医疗主题）
    var crossV = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.2, 0.03), accentMat);
    crossV.position.set(0, 0.42, 0.29); g.add(crossV);
    var crossH = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.06, 0.03), accentMat);
    crossH.position.set(0, 0.42, 0.29); g.add(crossH);

    // 手臂（上臂自肩外撇、小臂向内收，双手托住牌子下缘，姿势自然）
    var upperGeo = new THREE.CapsuleGeometry(0.06, 0.22, 6, 10);
    var foreGeo = new THREE.CapsuleGeometry(0.055, 0.5, 6, 10);
    var upperL = new THREE.Mesh(upperGeo, bodyMat);
    upperL.position.set(-0.46, 0.7, 0.06); upperL.rotation.z = 0.62;
    upperL.castShadow = true; g.add(upperL);
    var foreL = new THREE.Mesh(foreGeo, bodyMat);
    foreL.position.set(-0.495, 1.14, 0.09); foreL.rotation.z = -0.21;
    foreL.castShadow = true; g.add(foreL);
    var upperR = new THREE.Mesh(upperGeo, bodyMat);
    upperR.position.set(0.46, 0.7, 0.06); upperR.rotation.z = -0.62;
    upperR.castShadow = true; g.add(upperR);
    var foreR = new THREE.Mesh(foreGeo, bodyMat);
    foreR.position.set(0.495, 1.14, 0.09); foreR.rotation.z = 0.21;
    foreR.castShadow = true; g.add(foreR);

    // 欢迎牌（双手举在头顶上方）
    var signG = new THREE.Group();
    var board = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.5, 0.05),
      new THREE.MeshToonMaterial({ color: 0xf2f7fa, gradientMap: gradientMap }));
    signG.add(board);
    // 牌子蓝色边框
    var frame = new THREE.Mesh(new THREE.BoxGeometry(0.94, 0.54, 0.03), accentMat);
    frame.position.z = -0.02; signG.add(frame);
    // 牌面文字
    var cv = document.createElement("canvas"); cv.width = 512; cv.height = 288;
    var ctx2 = cv.getContext("2d");
    ctx2.fillStyle = "#f7fafc"; ctx2.fillRect(0, 0, 512, 288);
    ctx2.fillStyle = "#1387c0"; ctx2.font = "bold 128px sans-serif";
    ctx2.textAlign = "center"; ctx2.textBaseline = "middle";
    ctx2.fillText("你 好", 256, 112);
    ctx2.font = "bold 40px sans-serif"; ctx2.fillStyle = "#4a6076";
    ctx2.fillText("MedTriage · 智能导诊", 256, 220);
    var signTex = new THREE.CanvasTexture(cv);
    var signFace = new THREE.Mesh(new THREE.PlaneGeometry(0.86, 0.46),
      new THREE.MeshBasicMaterial({ map: signTex }));
    signFace.position.z = 0.028; signG.add(signFace);
    signG.position.set(0, 1.72, 0.1); g.add(signG);
    // 手：贴在牌子下缘两角，随牌子一起晃动（托举感）
    var handL = new THREE.Mesh(new THREE.SphereGeometry(0.075, 12, 10), accentMat);
    handL.position.set(-0.43, -0.28, 0); handL.castShadow = true; signG.add(handL);
    var handR = handL.clone(); handR.position.x = 0.43; signG.add(handR);
    g.userData.signG = signG;
    g.userData.eyeL = eyeL;
    g.userData.eyeR = eyeR;

    // 脚（两个深色半球像小轮子）
    var footL = new THREE.Mesh(new THREE.SphereGeometry(0.14, 12, 10, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2), darkMat);
    footL.position.set(-0.16, 0.1, 0); footL.castShadow = true; g.add(footL);
    var footR = footL.clone(); footR.position.x = 0.16; g.add(footR);

    // 起始位置：门诊大厅内（z=0.2），透过玻璃门可见
    g.position.set(0, 0, 0.2);
    g.scale.set(1.1, 1.1, 1.1);
    world.add(g);
    return g;
  })();

  /* ============================================================
     动画循环
     ============================================================ */
  var clock = new THREE.Clock();
  function smooth(x) { return x * x * (3 - 2 * x); }

  function animate(t) {
    // 自动门：7 秒一轮（1s 开 → 停 3s → 1s 关 → 停 2s）
    var cycle = t % 7, open;
    if (cycle < 1) open = smooth(cycle);
    else if (cycle < 4) open = 1;
    else if (cycle < 5) open = 1 - smooth(cycle - 4);
    else open = 0;
    doorL.position.x = -0.79 - open * 1.5;
    doorR.position.x = 0.79 + open * 1.5;

    // 小机器人：0.8s 开始走 → 3.8s 中速走出到门外广场 → 之后一直站门外左右晃牌子欢迎
    var walkStart = 0.8, walkEnd = 3.8;
    var rZ, rBounce, rSway;
    if (t < walkStart) {
      // 门内大厅待命（透过玻璃门可见）
      rZ = 0.2; rBounce = 0; rSway = 0;
      if (robot.userData.signG) {
        robot.userData.signG.rotation.z = 0;
      }
    } else if (t < walkEnd) {
      // 中速走出来（带走路弹跳）
      var p = smooth((t - walkStart) / (walkEnd - walkStart));
      rZ = 0.2 + p * 4.6; // 从 z=0.2（大厅内）走到 z=4.8（门外广场）
      rBounce = Math.abs(Math.sin(t * 5)) * 0.1;
      rSway = Math.sin(t * 5) * 0.06; // 走路时轻微左右摆
      if (robot.userData.signG) {
        robot.userData.signG.rotation.z = Math.sin(t * 5) * 0.05;
      }
    } else {
      // 站定门外，一直左右晃牌子表示欢迎
      rZ = 4.8;
      rBounce = Math.sin(t * 1.6) * 0.04; // 轻微呼吸浮动
      rSway = Math.sin(t * 1.2) * 0.08;   // 身体缓慢左右倾斜
      if (robot.userData.signG) {
        robot.userData.signG.rotation.z = Math.sin(t * 2.2) * 0.25; // 牌子明显左右晃
        robot.userData.signG.rotation.x = -0.1 + Math.sin(t * 2.2) * 0.05; // 牌子轻微前倾摆动
      }
      // 眼睛偶尔眨一下（每 4 秒眯眼 0.15 秒）
      var blinkCycle = t % 4;
      var eyeScale = blinkCycle > 3.8 ? 0.1 : 1.0;
      if (robot.userData.eyeL) {
        robot.userData.eyeL.scale.y = 1.3 * eyeScale;
        robot.userData.eyeR.scale.y = 1.3 * eyeScale;
      }
    }
    robot.position.z = rZ;
    robot.position.y = rBounce;
    robot.rotation.y = rSway;

    // 树冠轻摆
    for (var i = 0; i < crowns.length; i++) {
      var c = crowns[i], ph = c.userData.phase;
      c.rotation.z = Math.sin(t * 1.1 + ph) * 0.045;
      c.rotation.x = Math.cos(t * 0.9 + ph) * 0.03;
    }
    // 涟漪扩散
    for (var r = 0; r < ripples.length; r++) {
      var ring = ripples[r], ph2 = (t * 0.32 + ring.userData.phase) % 1;
      var s = 0.4 + ph2 * 1.9;
      ring.scale.set(s, s, s);
      ring.material.opacity = 0.6 * (1 - ph2);
    }
    // 救护车警示灯 红蓝交替
    if (beaconL && beaconR) {
      var blink = Math.floor(t * 2.4) % 2 === 0;
      beaconL.material.color.setHex(blink ? 0xff3524 : 0x7a1d12);
      beaconR.material.color.setHex(blink ? 0x16265e : 0x2f6bff);
    }
    // 白云漂移（出界回绕）
    for (var k = 0; k < clouds.length; k++) {
      var cl = clouds[k];
      cl.position.x += cl.userData.speed * 0.016;
      if (cl.position.x > 30) cl.position.x = -30;
    }
    // 光斑缓慢漂移
    var spots = world.userData.spots;
    if (spots) {
      spots.position.x = 2.5 + Math.sin(t * 0.1) * 1.6;
      spots.rotation.z = t * 0.02;
    }
  }

  /* ---------- 渲染调度：可见时才渲染，减少运动偏好时按需渲染 ---------- */
  var inView = true, stopped = false, rafId = 0, io = null, ro = null;
  if ("IntersectionObserver" in window) {
    io = new IntersectionObserver(function (entries) {
      inView = entries[0].isIntersecting;
    }, { threshold: 0.02 });
    io.observe(wrap);
  }

  function frame() {
    if (stopped) return;
    rafId = requestAnimationFrame(frame);
    if (!inView) return;
    if (!reduceMotion) animate(clock.getElapsedTime());
    controls.update();
    renderer.render(scene, camera);
  }

  /* ---------- 自适应尺寸 ---------- */
  function resize() {
    if (stopped) return;
    var w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    if (reduceMotion) renderer.render(scene, camera);
  }
  if ("ResizeObserver" in window) {
    ro = new ResizeObserver(resize);
    ro.observe(canvas);
  } else {
    window.addEventListener("resize", resize);
  }
  resize();

  if (reduceMotion) {
    // 静态：交互变化时才重绘
    animate(2.5); // 门保持打开姿态，方便看清大厅
    controls.addEventListener("change", function () { if (!stopped) renderer.render(scene, camera); });
    renderer.render(scene, camera);
  } else {
    frame();
  }

  /* ---------- 清理：离开落地页时由 heroScene.ts 调用 ---------- */
  return function cleanup() {
    if (stopped) return;
    stopped = true;
    cancelAnimationFrame(rafId);
    if (idleTimer) clearTimeout(idleTimer);
    if (firstRotateTimer) clearTimeout(firstRotateTimer);
    if (io) io.disconnect();
    if (ro) ro.disconnect();
    window.removeEventListener("resize", resize);
    controls.dispose();
    scene.traverse(function (o) {
      if (o.geometry) o.geometry.dispose();
      var mats = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : [];
      mats.forEach(function (m) { if (m.map) m.map.dispose(); m.dispose(); });
    });
    gradientMap.dispose();
    renderer.dispose();
    if (renderer.forceContextLoss) renderer.forceContextLoss();
  };
  };
})();
