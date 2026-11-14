"""边界保守分诊的阈值标定（Task 1.2 的配套脚本，纯离线）。

回答一个具体问题：BORDERLINE_GAP 取 0.12 时，
  · 有多少张「真实分级被模型低估」的样本会被升级救回？
  · 代价是多少张本来判对的样本被多要求一次复查？

只读 test 留出集（508 张），不改任何模型与阈值，输出一张 trade-off 表。
用法（backend 目录下）：
    python evals/calibrate_borderline.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fundus import analyzer  # noqa: E402

DATA = r"C:\Users\Administrator\Desktop\DR_merged_classification\test"
GAPS = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20]
DEFAULT_GAP = 0.12  # 与 triage.BORDERLINE_GAP 的默认值保持一致


def main() -> None:
    if analyzer.is_demo:
        print("模型未加载（demo 模式），无法标定。请确认 torch + weights 可用。")
        return

    rows = []  # (true_level, pred_level, probs)
    total = 0
    for lv in range(5):
        d = os.path.join(DATA, str(lv))
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            with open(os.path.join(d, name), "rb") as f:
                data = f.read()
            try:
                out = analyzer.analyze(data)
            except Exception as e:  # 单张坏图不打断整体标定
                print(f"[skip] {name}: {type(e).__name__}")
                continue
            rows.append((lv, out["level"], out["probabilities"]))
            total += 1
            if total % 50 == 0:
                print(f"  已推理 {total} 张…")

    n = len(rows)
    print(f"\n样本数：{n}")

    # 基线：低估 / 高估 / 一致
    under = [r for r in rows if r[1] < r[0]]
    over = [r for r in rows if r[1] > r[0]]
    exact = [r for r in rows if r[1] == r[0]]
    print(f"一致 {len(exact)} / 低估 {len(under)} / 高估 {len(over)}")
    d32 = [r for r in under if r[0] == 3 and r[1] == 2]
    print(f"其中「真实 3 级被判 2 级」：{len(d32)} 张（这是最危险的方向）\n")

    print(f"{'gap':>6} {'救回低估':>10} {'救回3→2':>10} {'多升级(判对)':>14} {'多升级(判高)':>14}")
    print("-" * 62)
    for gap in GAPS:
        rescued = rescued32 = extra_ok = extra_over = 0
        for true_lv, pred_lv, probs in rows:
            if pred_lv >= 4:
                continue
            near = (probs[pred_lv] - probs[pred_lv + 1]) < gap
            if not near:
                continue
            if pred_lv < true_lv:          # 低估，升级方向正确
                rescued += 1
                if true_lv == 3 and pred_lv == 2:
                    rescued32 += 1
            elif pred_lv == true_lv:       # 本来判对，被多要求复查
                extra_ok += 1
            else:                          # 已经判高，继续升（无临床收益）
                extra_over += 1
        print(f"{gap:>6.2f} {rescued:>10} {rescued32:>10} {extra_ok:>14} {extra_over:>14}")

    # 默认阈值下的明细：多升级的到底是哪几级（0→1 只是文案微调，1→2 才是绿变黄）
    print(f"\n默认阈值 gap={DEFAULT_GAP:.2f} 的明细：")
    detail_ok, detail_rescued = {}, {}
    for true_lv, pred_lv, probs in rows:
        if pred_lv >= 4:
            continue
        if (probs[pred_lv] - probs[pred_lv + 1]) >= DEFAULT_GAP:
            continue
        if pred_lv == true_lv:
            k = f"{pred_lv}→{pred_lv + 1} 级（判对，多复查）"
            detail_ok[k] = detail_ok.get(k, 0) + 1
        elif pred_lv < true_lv:
            k = f"真实 {true_lv} / 判 {pred_lv}（救回）"
            detail_rescued[k] = detail_rescued.get(k, 0) + 1
    for k in sorted(detail_rescued):
        print(f"  [救回] {k}: {detail_rescued[k]} 张")
    for k in sorted(detail_ok):
        print(f"  [代价] {k}: {detail_ok[k]} 张")

    print("\n读法：gap 越大越保守——救回更多低估，也让更多判对的病例提前复查。")
    print("临床上「漏转诊」的代价远高于「多复查一次」，所以阈值应偏向救回。")
    print("注意：概率差阈值抓不住「自信地错」——3→2 的 13 张里只有少数是犹豫的。")
    print("这正是下一步要用病灶级标注而不是调阈值的原因。")


if __name__ == "__main__":
    main()
