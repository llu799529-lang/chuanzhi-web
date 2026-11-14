/**
 * 附近医院：高德 JS API 2.0 地图 + 周边 POI 检索 + 科室重排。
 * 逻辑平移自原生 app.js 的 AmapHosp 模块（阈值、排序、文案保持一致）。
 */

export interface AmapConf {
  amap_js_key?: string;
  amap_js_sec?: string;
  hospitals?: {
    name: string; level?: string; address?: string; distance_km?: number | null;
    phone?: string;
    /** 后端 / 高德给出的科室名。有它就优先用，没有才按医院名推断。 */
    depts?: string[];
  }[];
}

export interface Poi {
  name: string;
  type: string;
  address: string;
  distance: number | null;
  tel: string;
  location: { lng: number; lat: number } | null;
  /** 后端直接给出的科室（演示数据 / 高德扩展字段），缺失时由 hospitalProfile 按名字推断 */
  depts?: string[];
}

export interface HospitalProfile {
  depts: string[];
  specialized: boolean;
  topic: string;
}

export const DEPT_OPTIONS = [
  "眼科", "心血管内科", "神经内科", "神经外科", "内分泌科", "骨科",
  "呼吸内科", "消化内科", "普外科", "妇产科", "儿科", "口腔科",
  "中医科", "肿瘤科", "精神心理科", "皮肤科", "全科",
];

export function hospitalProfile(name: string, type = "", known?: string[]): HospitalProfile {
  // 后端给了科室就直接用。名称推断只适用于「名字里带专科特征」的医院
  // （眼科医院、口腔医院…），对「市第一人民医院」这种综合医院只能靠猜，
  // 猜出来的科室和用户实际要挂的科没有关系。
  if (known?.length) {
    return { depts: known, specialized: false, topic: "" };
  }
  const n = name || "";
  let depts: string[] = [];
  let specialized = false;
  let topic = "";
  if (/眼科|眼病|眼视光/.test(n)) {
    depts = ["眼底病", "白内障", "青光眼", "视光中心"];
    specialized = true;
    topic = "眼科疾病";
  } else if (/妇幼|妇产/.test(n)) {
    depts = ["妇产科", "产科", "儿科", "新生儿科"];
    specialized = true;
    topic = "妇儿健康";
  } else if (/儿童|儿科/.test(n)) {
    depts = ["儿科", "儿童保健", "小儿呼吸", "小儿外科"];
    specialized = true;
    topic = "儿童疾病";
  } else if (/口腔|牙科/.test(n)) {
    depts = ["口腔外科", "口腔正畸", "种植修复", "牙周科"];
    specialized = true;
    topic = "口腔诊疗";
  } else if (/中医/.test(n)) {
    depts = ["中医内科", "针灸推拿", "康复理疗", "治未病"];
    specialized = true;
    topic = "中医诊疗";
  } else if (/肿瘤/.test(n)) {
    depts = ["肿瘤内科", "肿瘤外科", "放疗科", "微创介入"];
    specialized = true;
    topic = "肿瘤防治";
  } else if (/精神|脑科|心理/.test(n)) {
    depts = ["精神心理科", "睡眠医学科", "神经内科"];
    specialized = true;
    topic = "精神心理";
  } else if (/骨科|骨伤/.test(n)) {
    depts = ["骨科", "脊柱外科", "关节外科", "运动康复"];
    specialized = true;
    topic = "骨伤康复";
  } else if (/心脏|心血管/.test(n)) {
    depts = ["心血管内科", "心脏外科", "介入科"];
    specialized = true;
    topic = "心血管疾病";
  } else if (/皮肤/.test(n)) {
    depts = ["皮肤科", "医学美容"];
    specialized = true;
    topic = "皮肤疾病";
  } else if (/社区/.test(n)) {
    return { depts: ["全科门诊", "慢病随访", "双向转诊", "预防保健"], specialized: true, topic: "基层诊疗" };
  }
  if (depts.length) return { depts, specialized, topic };

  if (/人民/.test(n)) depts = ["心血管内科", "骨科", "消化内科", "神经内科", "呼吸内科", "普外科"];
  else if (/中心/.test(n)) depts = ["急诊医学", "心血管内科", "神经外科", "重症医学科", "妇产科"];
  else if (/大学|附属|医大/.test(n)) depts = ["心血管内科", "神经外科", "眼科", "骨科", "肿瘤科", "内分泌科"];
  else if (/第一|第二|第三/.test(n)) depts = ["呼吸内科", "消化内科", "普外科", "骨科", "妇产科"];
  else depts = ["内科", "外科", "妇产科", "儿科", "骨科", "眼科"];
  return { depts, specialized: false, topic };
}

export function levelTag(type: string, name: string): string {
  const s = `${type || ""}${name || ""}`;
  if (/三级甲等/.test(s)) return "三级甲等";
  if (/三级/.test(s)) return "三级医院";
  if (/二级甲等/.test(s)) return "二级甲等";
  if (/二级/.test(s)) return "二级医院";
  if (/一级/.test(s)) return "一级医院";
  if (/专科/.test(type || "")) return "专科医院";
  if (/社区/.test(s)) return "社区医院";
  return "综合医院";
}

export function deptHit(depts: string[], name: string, rec: string): number {
  const key = rec.replace(/科$/, "");
  if (!key) return -1;
  for (let i = 0; i < depts.length; i++) if (depts[i].includes(key)) return i;
  return (name || "").includes(key) ? 0 : -1;
}

export function distTxt(m: number | null): string {
  if (m == null) return "";
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}

export function genIntro(name: string, tag: string, info: HospitalProfile): string {
  const n = name || "";
  const leads = info.depts.slice(0, 3).join("、");
  const t = /综合医院|专科医院|社区医院|诊所|门诊部/.test(tag) ? tag : `${tag}综合医院`;
  if (info.specialized) {
    return `${n}为${t}，${info.topic ? `专注${info.topic}，` : ""}以${leads}等为特色科室，同时开设普通门诊接诊常见病、多发病。`;
  }
  if (/社区/.test(n)) {
    return `${n}承担周边社区居民常见病、多发病诊疗与慢病健康管理，提供全科门诊、双向转诊与家庭医生签约服务，是基层首诊的重要站点。`;
  }
  return `${n}为${t}，以${leads}等为重点科室，临床科室覆盖全面，可提供门诊、住院与急诊综合诊疗服务。`;
}

export function sortPois(pois: Poi[], recDept: string): Poi[] {
  return pois.slice().sort((a, b) => {
    const ha = deptHit(hospitalProfile(a.name, a.type, a.depts).depts, a.name, recDept) >= 0 ? 0 : 1;
    const hb = deptHit(hospitalProfile(b.name, b.type, b.depts).depts, b.name, recDept) >= 0 ? 0 : 1;
    return ha - hb || (a.distance ?? 9e9) - (b.distance ?? 9e9);
  });
}

/** 演示数据 → POI（无高德 Key 时的兜底，仍然比前端硬编码真实） */
export function confToPois(conf: AmapConf): Poi[] {
  return (conf.hospitals ?? []).map((h) => ({
    name: h.name,
    type: h.level || "综合医院",
    address: h.address || "",
    distance: h.distance_km != null ? h.distance_km * 1000 : null,
    tel: h.phone || "",
    location: null,
    depts: h.depts,
  }));
}

/* ---------------- 高德 SDK 极简类型 ---------------- */
interface AMapMarker {
  on: (ev: string, fn: () => void) => void;
  getPosition: () => unknown;
}
interface AMapMap {
  add: (o: unknown) => void;
  remove: (o: unknown) => void;
  setCenter: (p: [number, number]) => void;
  setFitView: (o: unknown, b?: boolean, pad?: number[]) => void;
  setZoomAndCenter: (z: number, p: unknown) => void;
}
export interface AMapNS {
  Map: new (el: HTMLElement, opts: Record<string, unknown>) => AMapMap;
  Marker: new (opts: Record<string, unknown>) => AMapMarker;
  plugin: (name: string, cb: () => void) => void;
  Geolocation: new (opts: Record<string, unknown>) => {
    getCurrentPosition: (cb: (status: string, r: { position?: { lng: number; lat: number } }) => void) => void;
  };
  CitySearch: new () => {
    getLocalCity: (cb: (s: string, r: { bounds?: { getCenter: () => { lng: number; lat: number } } }) => void) => void;
  };
  PlaceSearch: new (opts: Record<string, unknown>) => {
    searchNearBy: (
      kw: string,
      center: [number, number],
      radius: number,
      cb: (status: string, r: { poiList?: { pois: RawPoi[] } }) => void,
    ) => void;
  };
}
interface RawPoi {
  name: string;
  type?: string;
  address?: string;
  distance?: number;
  tel?: string;
  location?: { lng: number; lat: number };
}

let loading: Promise<AMapNS | null> | null = null;

export function loadAmapScript(key: string, sec: string): Promise<AMapNS | null> {
  if (loading) return loading;
  loading = new Promise((resolve) => {
    const w = window as unknown as { AMap?: AMapNS; _AMapSecurityConfig?: unknown };
    if (w.AMap) return resolve(w.AMap);
    if (!key) return resolve(null);
    if (sec) w._AMapSecurityConfig = { securityJsCode: sec };
    const s = document.createElement("script");
    s.src = `https://webapi.amap.com/maps?v=2.0&key=${key}&plugin=AMap.PlaceSearch,AMap.CitySearch,AMap.Geolocation`;
    s.onload = () => resolve((window as unknown as { AMap?: AMapNS }).AMap ?? null);
    s.onerror = () => resolve(null);
    document.head.appendChild(s);
  });
  return loading;
}

export interface MapController {
  draw: (pois: Poi[], recDept: string, onSelect: (i: number) => void) => void;
  focus: (pois: Poi[], i: number) => void;
}

/** 建图 → 定位（浏览器，失败退城市中心）→ 周边 10km 医院检索 */
export function setupMap(
  el: HTMLElement,
  AMap: AMapNS,
  onPois: (pois: Poi[]) => void,
  onFail: (msg: string) => void,
): Promise<MapController> {
  const map = new AMap.Map(el, { zoom: 13, viewMode: "2D", mapStyle: "amap://styles/fresh" });
  let markers: AMapMarker[] = [];

  // 兜底中心：定位全部失败时**仍然要出图**。原先两个定位手段都失败时只调 onFail
  // 就 return，Promise 永远不 resolve —— 底图在、一个医院点位都没有，
  // 用户看到的就是「地图没标医院」。宁可给默认城市，也不要给一张空图。
  const FALLBACK_CENTER = { lng: 116.397428, lat: 39.90923 };

  const locate = (cb: (pos: { lng: number; lat: number }, isFallback: boolean) => void) => {
    AMap.plugin("AMap.Geolocation", () => {
      const geo = new AMap.Geolocation({ enableHighAccuracy: false, timeout: 3500 });
      geo.getCurrentPosition((status, result) => {
        if (status === "complete" && result.position) return cb(result.position, false);
        AMap.plugin("AMap.CitySearch", () => {
          new AMap.CitySearch().getLocalCity((s2, r2) => {
            const c = r2.bounds?.getCenter();
            if (s2 === "complete" && c) return cb(c, false);
            onFail("无法获取定位，已按默认城市展示附近医院");
            cb(FALLBACK_CENTER, true);
          });
        });
      });
    });
  };

  // 看门狗：`AMap.plugin` 的回调在某些情况下**根本不会触发**
  // （key 未开通插件权限、webapi.amap.com 被墙、安全密钥不匹配）。
  // 那种情况下既没有点位也没有报错，用户看到的是一张永远空着的地图，
  // 而且页面上连"为什么"都没有。8 秒没结果就明说原因，别让它静默空着。
  let settled = false;
  let watchdog: ReturnType<typeof setTimeout> | null = null;

  return new Promise((resolve) => {
    const settle = (msg?: string) => {
      if (settled) return;
      settled = true;
      if (watchdog) clearTimeout(watchdog);
      if (msg) onFail(msg);
      resolve({ draw: () => undefined, focus: () => undefined });
    };
    watchdog = setTimeout(() => {
      settle("地图服务 8 秒无响应：请确认高德 JS Key 已开通「PlaceSearch」插件权限，" +
             "且安全密钥与 Key 匹配（控制台 → 应用管理）");
    }, 8000);

    locate((pos, isFallback) => {
      const lnglat: [number, number] = [pos.lng, pos.lat];
      // 兜底中心不是用户真实位置，不能标「当前位置」——那是在骗用户
      if (!isFallback) {
        map.add(
          new AMap.Marker({
            position: lnglat,
            anchor: "bottom-center",
            zIndex: 120,
            content: '<div class="amk me"><div class="dot"></div><div class="lbl">当前位置</div></div>',
          }),
        );
      }
      map.setCenter(lnglat);

      AMap.plugin("AMap.PlaceSearch", () => {
        const ps = new AMap.PlaceSearch({ pageSize: 45, pageIndex: 1, extensions: "base" });
        const attempt = (radius: number) => ps.searchNearBy("医院", lnglat, radius, (status, result) => {
          const raw = result.poiList?.pois ?? [];
          if (status !== "complete" || !raw.length) {
            // 10km 内没结果在郊区/新城区很常见，放大到 20km 再试一次。
            // 直接放弃 = 用户看到永远空着的地图。
            if (radius < 20000) return attempt(20000);
            settle("未检索到附近医院，请稍后重试");
            return;
          }
          const pois: Poi[] = raw
            .filter((p) => p.location && (/医院/.test(p.name) || /医疗/.test(p.type || "")))
            .map((p) => ({
              name: p.name,
              type: p.type || "",
              address: p.address || "",
              distance: p.distance ?? null,
              tel: p.tel || "",
              location: p.location ?? null,
            }));
          onPois(pois);
          settled = true;
          if (watchdog) clearTimeout(watchdog);

          resolve({
            draw(list: Poi[], recDept: string, onSelect: (i: number) => void) {
              if (markers.length) {
                map.remove(markers);
                markers = [];
              }
              list.forEach((p, i) => {
                if (!p.location) return;
                const hit = deptHit(hospitalProfile(p.name, p.type).depts, p.name, recDept) >= 0;
                const mk = new AMap.Marker({
                  position: [p.location.lng, p.location.lat],
                  anchor: "bottom-center",
                  title: p.name,
                  content:
                    `<div class="amk${hit ? " hit" : ""}"><div class="dot">${i + 1}</div>` +
                    `<div class="lbl">${escHtml(p.name)}</div></div>`,
                });
                mk.on("click", () => onSelect(i));
                map.add(mk);
                markers.push(mk);
              });
              if (markers.length) map.setFitView(markers, false, [60, 60, 60, 60]);
            },
            focus(list: Poi[], i: number) {
              const p = list[i];
              if (p?.location) map.setZoomAndCenter(15, [p.location.lng, p.location.lat]);
            },
          });
        });
        attempt(10000);
      });
    });
  });
}

export function escHtml(t: string): string {
  return String(t ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function navUrl(p: Poi): string {
  if (!p.location) return "";
  return (
    "https://uri.amap.com/navigation?to=" +
    encodeURIComponent(`${p.location.lng},${p.location.lat},${p.name}`) +
    "&mode=car&coordinate=gaude&src=MedTriage"
  );
}

// ---------------------------------------------------------------- 工作台「附近医院」卡片：不建地图的周边检索
export interface NearbyResult {
  pois: Poi[];
  /** true：浏览器定位失败，距离按 IP 所在城市中心估算 */
  approximate: boolean;
  at: number;
}

const NEARBY_KEY = "mt_nearby_hospitals_v1";

/** 最近一次真实检索结果。用 sessionStorage：关掉标签页即清除，不长期保存与位置有关的数据。 */
export const nearbyCache = {
  get(maxAgeMs = 30 * 60_000): NearbyResult | null {
    try {
      const raw = sessionStorage.getItem(NEARBY_KEY);
      if (!raw) return null;
      const r = JSON.parse(raw) as NearbyResult;
      return Array.isArray(r.pois) && r.pois.length && Date.now() - r.at < maxAgeMs ? r : null;
    } catch {
      return null;
    }
  },
  set(pois: Poi[], approximate = false): void {
    try {
      sessionStorage.setItem(NEARBY_KEY, JSON.stringify({ pois: pois.slice(0, 15), approximate, at: Date.now() }));
    } catch {
      /* 存不下就不缓存 */
    }
  },
};

function toPois(raw: RawPoi[]): Poi[] {
  return raw
    .filter((p) => p.location && (/医院/.test(p.name) || /医疗/.test(p.type || "")))
    .map((p): Poi => ({ name: p.name, type: p.type || "", address: p.address || "", distance: p.distance ?? null, tel: p.tel || "", location: p.location ?? null }))
    .sort((a, b) => (a.distance ?? Infinity) - (b.distance ?? Infinity));
}

/**
 * 定位 → 周边 10 km（没结果放大到 20 km）医院检索，不建地图。
 * 只返回高德的真实结果；没 Key、定位失败、超时都报错说明原因，不拿演示数据凑数。
 */
export async function findNearbyHospitals(conf: AmapConf, timeoutMs = 12_000): Promise<NearbyResult> {
  const key = (conf.amap_js_key || "").trim();
  if (!key) throw new Error("地图未启用：在项目根目录 .env 填写 AMAP_JS_KEY 后重启服务");
  const AMap = await loadAmapScript(key, conf.amap_js_sec || "");
  if (!AMap) throw new Error("地图服务加载失败：请检查网络后重试");
  return new Promise<NearbyResult>((resolve, reject) => {
    let done = false;
    const finish = (err: Error | null, r?: NearbyResult) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      if (err) reject(err);
      else resolve(r as NearbyResult);
    };
    const timer = setTimeout(() => finish(new Error("地图服务暂时无响应，可以到「附近医院」页查看")), timeoutMs);
    const search = (center: { lng: number; lat: number }, approximate: boolean) => {
      AMap.plugin("AMap.PlaceSearch", () => {
        const ps = new AMap.PlaceSearch({ pageSize: 30, pageIndex: 1, extensions: "base" });
        const attempt = (radius: number) =>
          ps.searchNearBy("医院", [center.lng, center.lat], radius, (status, result) => {
            const pois = status === "complete" ? toPois(result.poiList?.pois ?? []) : [];
            if (!pois.length && radius < 20000) return attempt(20000);
            if (!pois.length) return finish(new Error("附近没有检索到医院"));
            nearbyCache.set(pois, approximate);
            finish(null, { pois, approximate, at: Date.now() });
          });
        attempt(10000);
      });
    };
    AMap.plugin("AMap.Geolocation", () => {
      const geo = new AMap.Geolocation({ enableHighAccuracy: false, timeout: 5000 });
      geo.getCurrentPosition((status, result) => {
        if (status === "complete" && result.position) return search(result.position, false);
        AMap.plugin("AMap.CitySearch", () => {
          new AMap.CitySearch().getLocalCity((s2, r2) => {
            const c = r2.bounds?.getCenter();
            if (s2 === "complete" && c) return search(c, true);
            finish(new Error("无法获取定位：请允许浏览器定位，或到「附近医院」页查看"));
          });
        });
      });
    });
  });
}
