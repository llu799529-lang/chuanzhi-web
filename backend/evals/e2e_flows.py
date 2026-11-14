"""按「用户点击路径」跑一遍所有页面的后端调用 —— 这是补上之前验证盲区的脚本。

为什么要写这个
--------------
之前我做的「全端点冒烟」是**按接口测的**：自己造 token、自己拼 JSON。
但用户是**按页面点的**，而页面发出去的请求形态和我手写的不一样：

  · 对话页「点 + 选图就发」→ `text=""` + file  （这个形态我漏了，线上直接 400）
  · 综合分析页 → `{}` + 已有历史记录          （这个形态我漏了，线上 502）
  · 眼底页 → multipart 图片
  · 医院页 → GET 带 department / lat / lng

于是「14/14 通过」和「一登录就两个报错」同时成立——测的维度错了。
这个脚本按**页面**组织，每个用例对应一次真实点击，并且断言的不只是状态码，
还有返回体里页面真正会读的字段（否则 200 也可能是空壳）。

用法（服务要在跑）：
    cd backend && python evals/e2e_flows.py
    python evals/e2e_flows.py --base http://127.0.0.1:8010
    python evals/e2e_flows.py --fast        # 跳过耗时的 LLM 用例
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE_IMG = ROOT / "_shots" / "fundus_real.jpg"


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.token = ""
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _open(self, req, timeout):
        return self.opener.open(req, timeout=timeout)

    def json(self, path, data=None, method=None, timeout=60):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, method=method or ("POST" if body else "GET"))
        if body:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with self._open(req, timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:200]

    def form(self, path, fields: dict, file_field=None, file_bytes=None,
             filename="upload.jpg", ctype="image/jpeg", timeout=180):
        boundary = "----e2e" + uuid.uuid4().hex
        body = b""
        for k, v in fields.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
        if file_field:
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
                     f"filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
            body += file_bytes + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.base + path, data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with self._open(req, timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()[:300]

    def sse(self, path, fields, file_bytes=None, timeout=180):
        """读完整条 SSE，返回事件名列表与 error 文本。"""
        code, raw = self.form(path, fields, "file" if file_bytes else None, file_bytes, timeout=timeout)
        if code != 200:
            return code, [], raw.decode("utf-8", "replace")[:200]
        events, err = [], None
        for line in raw.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if line.startswith("event:"):
                events.append(line[6:].strip())
            elif line.startswith("data:") and '"message"' in line:
                err = line[5:].strip()[:160]
        return code, events, err


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--fast", action="store_true", help="跳过 LLM 用例（只验结构与鉴权）")
    ap.add_argument("--user", default="", help="用固定账号，默认随机新用户")
    a = ap.parse_args()

    c = Client(a.base)
    name = a.user or ("e2e" + uuid.uuid4().hex[:6])

    # ---------- 登录页 ----------
    st, d = c.json("/api/auth/register", {"username": name, "password": "test123456"})
    if st != 200:
        print(f"[FATAL] 注册失败 {st} {d}")
        return 2
    c.token = d["token"]
    print(f"账号：{name}")

    img = SAMPLE_IMG.read_bytes() if SAMPLE_IMG.exists() else b""
    if not img:
        print(f"[WARN] 找不到样例图片 {SAMPLE_IMG}，图片相关用例会跳过")
    results = []

    def run(title, fn):
        t0 = time.time()
        try:
            ok, detail = fn()
        except Exception as e:  # 网络/超时都算失败，但要看到原因
            ok, detail = False, f"{type(e).__name__}: {str(e)[:120]}"
        results.append((title, ok, detail, round(time.time() - t0, 1)))
        print(("  PASS " if ok else "  FAIL ") + f"{title}  {detail}  ({results[-1][3]}s)")

    # ---------- 工作台首页 ----------
    def health():
        st, h = c.json("/api/health")
        caps = h.get("capabilities") or {}
        need = ["fundus_model", "llm", "amap_map", "amap_poi"]
        miss = [k for k in need if k not in caps]
        return st == 200 and not miss, f"{st} llm_model={h.get('llm_model')} 缺字段={miss}"
    run("首页 · /api/health", health)

    def records_empty():
        st, d = c.json("/api/records")
        return st == 200 and "records" in d and "usage" in d, f"{st} keys={sorted(d) if isinstance(d, dict) else d}"
    run("历史页 · 空列表", records_empty)

    # ---------- 症状分诊页 ----------
    def symptom():
        st, d = c.json("/api/ai/symptom", {"text": "最近头晕头痛一周"}, timeout=120)
        ok = st == 200 and bool(d.get("dept")) and bool(d.get("suspects"))
        return ok, f"{st} dept={d.get('dept') if isinstance(d, dict) else d}"
    if a.fast:
        run("症状页 · /api/ai/symptom", lambda: (True, "skip(--fast)"))
    else:
        run("症状页 · /api/ai/symptom", symptom)

    # ---------- 眼底页 ----------
    def fundus():
        if not img:
            return True, "skip(无样图)"
        st, raw = c.form("/api/fundus/analyze", {}, "file", img, "f.jpg")
        if st != 200:
            return False, f"{st} {raw.decode('utf-8','replace')[:120]}"
        d = json.loads(raw)
        return "level" in d and "probabilities" in d, f"{st} level={d.get('level')} mode={d.get('mode')}"
    run("眼底页 · /api/fundus/analyze", fundus)

    # ---------- 化验单页 ----------
    def lab():
        if not img:
            return True, "skip(无样图)"
        st, raw = c.form("/api/ai/image", {}, "file", img, "lab.jpg", timeout=180)
        if st != 200:
            return False, f"{st} {raw.decode('utf-8','replace')[:120]}"
        d = json.loads(raw)
        return bool(d.get("kind")), f"{st} kind={d.get('kind')}"
    if a.fast:
        run("化验单页 · /api/ai/image", lambda: (True, "skip(--fast)"))
    else:
        run("化验单页 · /api/ai/image", lab)

    # ---------- 对话页：文字 ----------
    def chat_text():
        code, ev, err = c.sse("/api/agent/chat/stream", {"text": "最近头晕头痛一周"})
        # 第一轮可能是 ask，也可能直接 final；两者都算正常
        ok = code == 200 and ("ask" in ev or "final" in ev) and not err
        return ok, f"{code} events={sorted(set(ev))} err={err}"
    if a.fast:
        run("对话页 · 文字", lambda: (True, "skip(--fast)"))
    else:
        run("对话页 · 文字提问", chat_text)
        c.json("/api/agent/reset", {}, method="POST")

    # ---------- 对话页：只传图片（线上报过的 400） ----------
    def chat_image_only():
        if not img:
            return True, "skip(无样图)"
        code, ev, err = c.sse("/api/agent/chat/stream", {"text": ""}, img)
        ok = code == 200 and not err and bool(ev)
        return ok, f"{code} events={sorted(set(ev))} err={err}"
    if a.fast:
        run("对话页 · 纯图片（曾经 400）", lambda: (True, "skip(--fast)"))
    else:
        run("对话页 · 纯图片（曾经 400）", chat_image_only)
        c.json("/api/agent/reset", {}, method="POST")

    # ---------- 综合分析页（线上报过的 502） ----------
    def multimodal():
        st, d = c.json("/api/ai/multimodal", {}, timeout=180)
        if st != 200:
            return False, f"{st} {str(d)[:140]}"
        # 断言页面真正读的字段（MultiPage.vue 的 MultiResult: intro + findings），
        # 不是「有个 summary 就行」——后端从 schema 改版后就再没返回过 summary，
        # 这条断言一直红着没人发现，说明它的期望值是过时的。
        ok = isinstance(d, dict) and "intro" in d and isinstance(d.get("findings"), list)
        return ok, f"{st} keys={sorted(d)[:6]} findings={len(d.get('findings') or [])}"
    if a.fast:
        run("多模态页 · /api/ai/multimodal", lambda: (True, "skip(--fast)"))
    else:
        run("多模态页 · 有记录时（曾经 502）", multimodal)

    # ---------- 医院页 ----------
    def hospitals():
        # 必须 URL 编码：`urllib.request.Request` 拼中文直接抛
        # UnicodeEncodeError('ascii' codec can't encode)，看起来像服务端 500，
        # 实际是客户端连请求都没发出去。浏览器会自动编码，所以前端从来没暴露过。
        st, d = c.json("/api/hospitals?department=" + urllib.parse.quote("眼科"))
        ok = st == 200 and isinstance(d.get("hospitals"), list) and d.get("hospitals")
        return ok, f"{st} source={d.get('source')} n={len(d.get('hospitals') or [])}"
    run("医院页 · /api/hospitals", hospitals)

    def hospitals_geo():
        p = "/api/hospitals?department=" + urllib.parse.quote("眼科") + "&lat=39.90&lng=116.40"
        st, d = c.json(p)
        ok = st == 200 and isinstance(d.get("hospitals"), list)
        return ok, f"{st} source={d.get('source')}"
    run("医院页 · 带坐标", hospitals_geo)

    # ---------- 历史页：有记录之后 ----------
    def records_after():
        st, d = c.json("/api/records")
        n = len(d.get("records") or []) if isinstance(d, dict) else -1
        used = (d.get("usage") or {}).get("month_used") if isinstance(d, dict) else None
        return st == 200 and n >= 1, f"{st} n={n} month_used={used}"
    run("历史页 · 应有记录", records_after)

    # ---------- 鉴权 ----------
    def auth_guard():
        saved, c.token = c.token, ""
        st, _ = c.json("/api/records")
        c.token = saved
        return st == 401, f"{st}"
    run("鉴权 · 无 token 应 401", auth_guard)

    ok_n = sum(1 for _, ok, _, _ in results if ok)
    print(f"\n{ok_n}/{len(results)} 通过")
    bad = [r for r in results if not r[1]]
    if bad:
        print("失败项：")
        for t, _, d, _ in bad:
            print(f"  · {t}: {d}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
