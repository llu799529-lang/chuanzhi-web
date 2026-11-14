"""眼底 DR 分级模型评测：把 kappa 从「本地训练日志里的一个数字」变成可复现指标。

背景
----
`docs/EVAL.md` 之前写的 `kappa 0.892 / acc 76.6%` 来自训练日志，仓库里没有
验证集划分清单，**第三方复现不了**。这在评审里是最容易被戳的一处：
你说模型准，但没法证明。现在有了 `DR_merged_classification/` 的真实划分
（train / valid / test，各含 0-4 五个类别目录），这件事就变成一个脚本。

评测口径（三条都要看清楚，否则数字会被误读）
--------------------------------------------
1. **用哪个 split**：默认 `test`。它是**真留出集**——`valid` 通常参与过
   早停/选模型，拿它报数会偏高。想对比训练日志时再用 `--split valid`。
2. **分辨率不匹配**：这套导出的图是 **224×224 缩略图**（Roboflow 预处理过），
   而模型训练用的是原始分辨率（APTOS 原图约 2000px）。推理管线是
   `Resize(300*1.14) + CenterCrop(300)`，等于把 224 放大到 342 再裁。
   **放大不增加信息**，所以这里的数字会低于训练日志里的数字。
   这不是「模型在测试集上崩了」，是「尺子和训练时不同」。两个数都要报，不能只报高的。
3. **TTA 与线上一致**：线上 `_predict_real` 做水平翻转平均，这里也做。
   评测口径必须等于上线口径，否则评的不是同一个东西。

用法（在 backend/ 目录下）：
    python evals/eval_fundus.py                       # test 全量
    python evals/eval_fundus.py --split valid         # 对比训练日志
    python evals/eval_fundus.py --limit 100           # 先跑 100 张看速度
    python evals/eval_fundus.py --data "D:/xxx/DR_merged_classification"

输出：evals/fundus_report.json + 控制台表格（含混淆矩阵）
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
# 汇总按 split **合并**写进同一个文件：评审要看的是「test 和 valid 各是多少」，
# 分两个文件会让人只看到最后跑的那一个，还可能把 valid 的数当成留出集。
# 逐图明细单独存，因为 1000+ 行会把汇总文件撑得没法读。
OUT_PATH = os.path.join(EVALS_DIR, "fundus_report.json")

# 数据集的默认位置。放成常量而不是写死在 argparse 里，是为了让「换机器」
# 只改一行；也不放进环境变量——这个路径属于**评测素材**，不是运行时配置。
DEFAULT_DATA = r"C:\Users\Administrator\Desktop\DR_merged_classification"

IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")


def _quadratic_kappa(y_true: list[int], y_pred: list[int], n_cls: int = 5) -> float:
    """二次加权 Kappa（QWK）。

    为什么是二次加权：DR 分级是**有序**的 0-4。把 0 级答成 4 级，比答成 1 级
    严重得多，普通 kappa 把这两种错误同等看待，会低估「差一点」的模型、
    也会放过「差很多」的模型。二次加权让惩罚随距离平方增长，这正好对应
    临床上「漏诊重度」比「轻度误判」危险得多。
    """
    n = len(y_true)
    if n == 0:
        return 0.0
    # 观测矩阵与期望矩阵
    obs = [[0] * n_cls for _ in range(n_cls)]
    for t, p in zip(y_true, y_pred):
        obs[t][p] += 1
    hist_t = [0] * n_cls
    hist_p = [0] * n_cls
    for t in y_true:
        hist_t[t] += 1
    for p in y_pred:
        hist_p[p] += 1
    num = den = 0.0
    for i in range(n_cls):
        for j in range(n_cls):
            w = ((i - j) ** 2) / ((n_cls - 1) ** 2)
            num += w * obs[i][j]
            den += w * (hist_t[i] * hist_p[j] / n)
    if den == 0:
        # 全部落在同一档且预测也全对：分母为 0。此时「完全一致」应记 1.0，
        # 而不是 0.0——返回 0 会把一个完美结果报成最差。
        return 1.0 if all(t == p for t, p in zip(y_true, y_pred)) else 0.0
    return 1 - num / den


def _iter_split(data_dir: str, split: str):
    root = os.path.join(data_dir, split)
    if not os.path.isdir(root):
        raise SystemExit(f"找不到 {root}，用 --data 指定数据集根目录")
    for cls in sorted(os.listdir(root)):
        cdir = os.path.join(root, cls)
        if not (os.path.isdir(cdir) and cls.isdigit()):
            continue
        label = int(cls)
        for fn in sorted(os.listdir(cdir)):
            if fn.lower().endswith(IMG_EXT):
                yield os.path.join(cdir, fn), label


def run(data_dir: str, split: str, limit: int | None = None) -> dict:
    import fundus

    if fundus.analyzer.is_demo:
        print("[跳过] 眼底模型处于演示模式（无权重或未装 torch），"
              "此时评出来的数字是伪随机的，没有任何意义。")
        return {}

    items = list(_iter_split(data_dir, split))
    if limit:
        # 分层抽样而不是取前 N 张：数据集是按类别目录排列的，直接截断
        # 会只取到 0 类，评出来的 accuracy 会虚高到离谱。
        per = max(1, limit // 5)
        buckets: dict[int, list] = {}
        for p, y in items:
            buckets.setdefault(y, []).append((p, y))
        items = [t for y in sorted(buckets) for t in buckets[y][:per]]

    y_true, y_pred, rows = [], [], []
    t0 = time.time()
    for i, (path, label) in enumerate(items, 1):
        try:
            with open(path, "rb") as f:
                out = fundus.analyzer.analyze(f.read())
        except Exception as e:  # 单张坏图不该让整个评测中断
            print(f"  [跳过坏图] {os.path.basename(path)}: {e}")
            continue
        pred = int(out["level"])
        y_true.append(label)
        y_pred.append(pred)
        rows.append({"file": os.path.basename(path), "label": label, "pred": pred,
                     "p_max": round(max(out["probabilities"]), 4)})
        if i % 50 == 0:
            acc = sum(1 for a, b in zip(y_true, y_pred) if a == b) / len(y_true)
            print(f"  {i}/{len(items)}  acc={acc:.3f}  {time.time() - t0:.0f}s", flush=True)

    n = len(y_true)
    acc = sum(1 for a, b in zip(y_true, y_pred) if a == b) / n if n else 0.0
    qwk = _quadratic_kappa(y_true, y_pred, 5)
    # 混淆矩阵：行=真实，列=预测
    cm = [[0] * 5 for _ in range(5)]
    for t, p in zip(y_true, y_pred):
        cm[t][p] += 1
    per_cls = []
    for c in range(5):
        tp = cm[c][c]
        support = sum(cm[c])
        pred_n = sum(cm[r][c] for r in range(5))
        per_cls.append({
            "class": c, "support": support,
            "recall": round(tp / support, 3) if support else None,
            "precision": round(tp / pred_n, 3) if pred_n else None,
        })
    # 「跨 2 级以上」的严重误判单独计数：这是临床上最不能接受的一类，
    # 平均准确率会把它稀释掉。
    severe = sum(1 for t, p in zip(y_true, y_pred) if abs(t - p) >= 2)

    report = {
        "split": split,
        "data_dir": data_dir,
        "n": n,
        "accuracy": round(acc, 4),
        "quadratic_kappa": round(qwk, 4),
        "severe_misgrade_2plus": severe,
        "severe_rate": round(severe / n, 4) if n else 0.0,
        "confusion_matrix": cm,
        "per_class": per_cls,
        "elapsed_s": round(time.time() - t0, 1),
        "caveat": ("数据集导出为 224x224 缩略图，推理管线会放大到 342 再裁 300；"
                   "训练用的是原始分辨率。分辨率不匹配会压低本指标，"
                   "不能与训练日志里的 kappa 直接对比。"),
    }
    rows_path = os.path.join(EVALS_DIR, f"fundus_rows_{split}.json")
    with open(rows_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    # 汇总合并进同一个文件，保留每个 split 各自的结果
    merged = {}
    if os.path.exists(OUT_PATH):
        try:
            merged = json.load(open(OUT_PATH, encoding="utf-8")).get("splits") or {}
        except (json.JSONDecodeError, OSError):
            merged = {}
    merged[split] = report
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"splits": merged,
                   "_note": "每个 split 独立一行。test 是真留出集，valid 参与过早停选模型，"
                            "对外报数用 test。逐图明细见 fundus_rows_<split>.json"},
                  f, ensure_ascii=False, indent=2)

    print()
    print(f"split={split}  n={n}  acc={report['accuracy']}  QWK={report['quadratic_kappa']}")
    print(f"跨 2 级以上误判 {severe} 张（{report['severe_rate']:.1%}）")
    print("每类：", "  ".join(
        f"{c['class']}:recall={c['recall']},n={c['support']}" for c in per_cls))
    print("混淆矩阵（行=真实，列=预测）：")
    for c in range(5):
        print("  ", c, cm[c])
    print(f"\n明细已写入 {OUT_PATH}（汇总）与 {rows_path}（逐图）")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA, help="DR 数据集根目录")
    ap.add_argument("--split", default="test", choices=["test", "valid", "train"])
    ap.add_argument("--limit", type=int, help="只评 N 张（按类别分层抽样）")
    a = ap.parse_args()
    run(a.data, a.split, a.limit)
