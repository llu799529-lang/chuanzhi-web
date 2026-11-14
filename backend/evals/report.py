"""MedTriage 评测报告（由 `python evals/report.py` 自动生成）。

不要手改本文件——数据来自真实运行结果，改了就失去可信度。
"""
import json
import os
import subprocess
import sys

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(EVALS_DIR)
sys.path.insert(0, BACKEND)


def _load(name):
    p = os.path.join(EVALS_DIR, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _signed(v, nd=3):
    """带符号小数；None 表示「消融无效」（向量通道没有真正启用），不能当 0 处理。"""
    return "N/A（向量通道未启用，消融无效）" if v is None else f"{v:+.{nd}f}"


def main():
    base = _load("baseline_v1.json")
    agent = _load("agent_scenarios.json") or {}
    inj = _load("prompt_injection.json") or {}

    lines = ["# MedTriage 评测报告", ""]
    lines += ["> 本文件由 `backend/evals/report.py` 自动生成，数据来自本机实测。", ""]

    # 眼底指标从 fundus_report.json 真读，不写死：这是本脚本自己的规矩（「改了就失去可信度」）。
    # 报告不存在时明确标「未跑」，而不是留一组看起来像实测的死数字。
    fr = _load("fundus_report.json") or {}
    t = (fr.get("splits") or {}).get("test") or {}
    if t:
        qwk, acc, n = f"{t['quadratic_kappa']:.4f}", f"{t['accuracy'] * 100:.2f}%", t["n"]
        caveat = fr.get("caveat") or t.get("caveat") or ""
        split_desc = f"test {n} 张"
    else:
        qwk = acc = split_desc = "未跑"
        caveat = "先执行 `python evals/eval_fundus.py --split test` 生成本报告"

    lines += ["## 1. 眼底分级模型", "",
              "| 指标 | 值 | 口径 |", "|---|---|---|",
              "| 骨干网络 | EfficientNet-B3 | torchvision |",
              "| 输入尺寸 | 300 × 300 | 推理时保持原生比例再 resize |",
              "| 分级体系 | DR 0–4（国际临床分级） | 5 分类 softmax |",
              f"| 二次加权 Kappa | {qwk} | {split_desc} |",
              f"| 准确率 | {acc} | {split_desc} top-1 |",
              "| 可解释性 | Grad-CAM 热力图 | 逐图输出，前端叠加显示 |", ""]
    if caveat:
        lines += [f"> 数据口径提示：{caveat}", ""]

    if base:
        lines += ["## 2. RAG 检索召回", "",
                  "| 指标 | 值 |", "|---|---|",
                  f"| 评测集 | {base.get('queries')} 条症状 query |",
                  f"| 命中（top3） | {base.get('hits')} |",
                  f"| recall@3 | **{base.get('recall_at_3')}** |",
                  f"| 检索引擎 | {base.get('engine')} |",
                  f"| 匹配口径 | {base.get('metric', '精确相等')} |", ""]

        miss = [r for r in base.get("results", []) if not r.get("hit")]
        if miss:
            lines += ["<details><summary>未命中明细（" + str(len(miss)) + " 条）</summary>", "",
                      "| query | 期望 | 实际 top3 |", "|---|---|---|"]
            for m in miss[:20]:
                lines.append(f"| {m['query']} | {', '.join(m['expect'])} | {', '.join(m['got']) or '（空）'} |")
            lines += ["", "</details>", ""]

    # 盲测（hold-out）章节：这一节是整份报告里最该被质疑、也最该被看的部分。
    # golden 的 50 条是边看结果边修出来的，高分只说明「这些句子能召回」。
    # 盲测批是在不知道结果的情况下写的，才反映换一批真实说法还能不能撑住。
    blind_path = os.path.join(EVALS_DIR, "blind_report.json")
    if os.path.isfile(blind_path):
        with open(blind_path, encoding="utf-8") as f:
            bl = json.load(f)
        s = bl.get("summary", {})
        full, no_vec = s.get("full", {}), s.get("no_vec", {})
        lines += ["## 2b. 盲测集（泛化能力）", "",
                  "上面 2 节的评测集是「边看结果边修」的，不能用来宣称泛化能力。"
                  "本节用的是写句子时不知道检索结果的独立样本，按批次分别统计。", "",
                  "| 批次 | 知识库轮次 | 条数 | recall@3（完整） | recall@3（关掉向量） | 向量贡献 |",
                  "|---|---|---|---|---|---|"]
        for b in bl.get("batches", []):
            f_, n_ = b["full"], b["no_vec"]
            mark = " ⚠️" if b.get("contaminated") else ""
            lines.append(
                f"| {b['batch']}{mark} | round {b.get('round')} | {f_['n']} | {f_['recall_at_3']:.3f} | "
                f"{n_['recall_at_3']:.3f} | {_signed(b.get('vec_delta'))} |"
            )
        lines += ["",
                  f"**合计**：{full.get('hits')}/{full.get('n')} = **{full.get('recall_at_3')}**；"
                  f"关掉向量通道后 {no_vec.get('recall_at_3')}，"
                  f"向量通道净贡献 **{_signed(s.get('vec_delta'))}**；"
                  f"hit@1 {full.get('hit_at_1', 'N/A')}、MRR@3 {full.get('mrr_at_3', 'N/A')}。", ""]
        lines += ["> **关于向量通道的坦白**：消融结果显示 fastembed（90MB 模型、首次加载 1.6s）"
                  f"带来的召回提升为 {_signed(s.get('vec_delta'))}（历史实测约 +0.025，在 D、E 两批上贡献为 0）。"
                  "原因是对短句的余弦相似度区分度太弱——实测「蹲下去站起来眼前一黑」全库 top1 是"
                  "「呕血 · 便血 · 黑便」0.507，而真正的正样本「心口像被压了块石头 → 胸痛」也只有 0.50，"
                  "正负样本完全重叠。因此它被定位为「关键词全空时的兜底通道」，阈值 0.55，"
                  "宁可不召回也不给自信的错误答案。若追求更小的部署体积，可以直接卸载 fastembed，"
                  "召回只掉 0.025。", ""]

        miss = [(b["batch"], r) for b in bl.get("batches", []) for r in b["full"]["rows"] if not r["hit"]]
        if miss:
            lines += [f"<details><summary>盲测未命中明细（{len(miss)} 条）</summary>", "",
                      "| 批次 | query | 期望 | 实际 top3 |", "|---|---|---|---|"]
            for bt, m in miss:
                lines.append(f"| {bt} | {m['query']} | {', '.join(m['expect'])} | {', '.join(m['got']) or '（空）'} |")
            lines += ["", "</details>", ""]

    lines += ["## 3. Agent 任务覆盖", "",
              f"评测集包含 **{len(agent.get('scenarios', []))}** 个场景，"
              "每个场景声明期望调用的工具集与期望报告类型。", "",
              "| # | 用户输入 | 期望工具 | 期望报告 |", "|---|---|---|---|"]
    for s in agent.get("scenarios", [])[:20]:
        lines.append(f"| {s['id']} | {s['input']} | {', '.join(s['expect_tools'])} | {s['expect_kind']} |")
    lines.append("")

    atk = inj.get("attacks", [])
    lines += ["## 4. Prompt 注入防御", "",
              f"**{len(atk)}** 条攻击样本，覆盖三类越界意图：", "",
              "| 类型 | 样本 | 期望行为 |", "|---|---|---|"]
    types = [
        ("直接要求诊断/开药", [a for a in atk if any(k in a for k in ("确诊", "诊断", "开药", "处方", "手术"))]),
        ("套取系统提示 / 工具定义", [a for a in atk if any(k in a for k in ("系统提示", "工具列表", "参数定义"))]),
        ("越权访问他人数据 / 重置系统", [a for a in atk if any(k in a for k in ("手机号", "历史记录", "管理员", "数据库"))]),
    ]
    for name, items in types:
        lines.append(f"| {name} | {'<br>'.join(items) or '—'} | 拒绝并回到筛查边界 |")
    lines += ["", "防御手段四层：", "",
              "1. **系统提示硬边界**：`SYMPTOM_SYSTEM` / `agent2.SYSTEM` 明确「不诊断、不开药」",
              "2. **入口检测围栏**：`guardrails.detect_injection` 命中后把用户原文围成「数据而非指令」，并给系统提示追加安全说明（不拒绝服务）",
              "3. **输出护栏扫描**：命中越界表述（确诊/处方/劝阻就医/具体剂量等）即标注 `needs_review`，只标注不改写",
              "4. **权限隔离**：工具只接受当前 JWT 用户，`get_history` 不接受外部传入的 username", ""]
    ir = _load("injection_report.json")
    if ir:
        det, og, gi = ir["detector"], ir["output_guard"], ir["gate_under_injection"]
        lines += ["### 规则层离线评测（`python evals/run_injection.py`）", "",
                  f"> {ir.get('scope', '')}", "",
                  "| 项 | 结果 | 口径 |", "|---|---|---|",
                  f"| 入口检测 · attacks | {det['attacks']['detected']}/{det['attacks']['n']} | {det['attacks']['note']} |",
                  f"| 入口检测 · variants | {det['variants']['detected']}/{det['variants']['n']} | {det['variants']['note']} |",
                  f"| 入口检测 · variants_2 | {det['variants_2']['detected']}/{det['variants_2']['n']} | {det['variants_2']['note']} |",
                  f"| 正常话术误报 | {det['benign']['false_positives']}/{det['benign']['n']} | {det['benign'].get('note', '正常患者话术')} |",
                  f"| 输出护栏 · 拦截越界输出 | {og['unsafe']['caught']}/{og['unsafe']['n']} | 越界词 {og['red_words']} 个 + 用药剂量正则 |",
                  f"| 输出护栏 · 误伤正常建议 | {og['safe']['false_positives']}/{og['safe']['n']} | |",
                  f"| 注入话术包裹下仍识别急症 | {gi['emergency_kept']}/{gi['n']} | 红旗闸门不依赖模型 |", ""]
        for key in ("variants", "variants_2"):
            for t in det[key].get("missed", []):
                lines.append(f"- {key} 漏检（原样保留，未为它改规则）：{t}")
        lines.append("")

    # 输出到独立文件，**不再覆盖 docs/EVAL.md**。
    #
    # 这里踩过一次真事故：本脚本原先把结果直接写进 docs/EVAL.md，
    # 而那份文档是手工精修的（含「能说/不能说」口径表、边界标定反证等
    # 脚本生成不出来的判断），跑一次脚本就把 405 行冲成 94 行，且没有 git 可回滚。
    # 自动生成的数字永远不该覆盖人工的判断，两者职责不同：
    #   docs/EVAL.md          → 人工精修的口径与结论（只由人写）
    #   docs/EVAL.generated.md → 本脚本的机器快照（每次覆盖，欢迎覆盖）
    out = os.path.join(os.path.dirname(BACKEND), "docs", "EVAL.generated.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"评测报告已写入 {out}（docs/EVAL.md 为人工精修版，脚本不会改动）")
    return out


if __name__ == "__main__":
    if not os.path.exists(os.path.join(EVALS_DIR, "baseline_v1.json")):
        print("先跑 evals/run_evals.py 生成基线")
        subprocess.run([sys.executable, os.path.join(EVALS_DIR, "run_evals.py")], check=False)
    main()
