"""DR 分级 → 科室映射与紧急程度。

分诊规则（与项目规划一致）：
  0–1 级：6–12 个月复查            → 绿色（常规）
  2 级：  3–6 个月眼科随诊          → 黄色（关注）
  3 级：  1 个月内眼科就诊          → 橙色（尽快）
  4 级：  尽快眼科就诊              → 红色（紧急）

v2（2026-10-19）：增加「边界病例保守升级」。当本级与高一级的概率差小于
BORDERLINE_GAP 时，**分级数字不变、紧急度按高一级走**——理由见常量注释。
"""
import os

DR_LEVELS = {
    0: {
        "name": "无明显视网膜病变",
        "department": "眼科（常规体检）",
        "urgency": "green",
        "urgency_label": "常规",
        "advice": "建议 6–12 个月内进行常规眼底复查。",
        "lesions": "未检出明显病灶",
        "red_flags": [],
    },
    1: {
        "name": "轻度非增殖期糖网（NPDR）",
        "department": "眼科",
        "urgency": "green",
        "urgency_label": "常规",
        "advice": "建议 6–12 个月内眼科复查，控制血糖血压。",
        "lesions": "可能存在少量微血管瘤",
        "red_flags": [],
    },
    2: {
        "name": "中度非增殖期糖网（NPDR）",
        "department": "眼科",
        "urgency": "yellow",
        "urgency_label": "需要关注",
        "advice": "建议 3–6 个月内眼科随诊，完善眼底检查。",
        "lesions": "微血管瘤、点状出血、硬性渗出",
        "red_flags": ["视力明显下降", "视物模糊持续加重"],
    },
    3: {
        "name": "重度非增殖期糖网（NPDR）",
        "department": "眼科",
        "urgency": "orange",
        "urgency_label": "尽快就诊",
        "advice": "建议 1 个月内眼科就诊，评估是否需进一步治疗。",
        "lesions": "大量出血、静脉串珠、棉绒斑",
        "red_flags": ["视力突然下降", "眼前黑影飘动增多", "视物变形"],
    },
    4: {
        "name": "增殖期糖网（PDR）",
        "department": "眼科（优先）",
        "urgency": "red",
        "urgency_label": "紧急",
        "advice": "建议尽快眼科就诊；如出现视力急剧下降，请立即前往急诊。",
        "lesions": "新生血管、玻璃体出血、纤维增殖",
        "red_flags": ["视力突然严重下降", "眼前大片黑影", "视野缺损"],
    },
}

DOCTOR_SUMMARY_TEMPLATE = (
    "筛查结果：DR {level} 级（{name}），模型置信度 {confidence:.0%}。"
    "图像质量：{quality}。主要可疑征象：{lesions}。"
    "建议转诊科室：{department}，随访建议：{advice}"
)

# 边界病例的保守升级阈值。
#
# 含义：当「当前级概率 − 下一级概率」小于这个值时，判定为分级边界。
#
# 为什么需要：3 级（重度 NPDR）在 test 集上 recall 只有 0.577，13/52 张被低估成
# 2 级——这是筛查场景里最危险的错误方向（该转诊的没转）。分级器本身不改
# （QWK 0.8958 保持可复现），改的是分诊层：不确定时按更严重的时限建议。
# 临床上的同构做法是钼靶 BI-RADS 0 类召回——影像不确定时先召回，而不是压成低危。
#
# 0.12 不是拍脑袋，是 test 留出集（508 张）上标定出来的拐点，
# 脚本：evals/calibrate_borderline.py（纯离线，可复现）：
#
#   gap     救回低估   其中救回 3→2   多升级(判对)   多升级(判高)
#   0.05       3           0              5            1
#   0.08       6           1              7            2
#   0.12       7           1              8            4      ← 默认
#   0.20      12           2             14            5
#
# 读法：0.12 时救回 7 张低估（含 1 张真实 4 级被判 2 级、1 张 3 级被判 2 级），
# 代价是 8 张判对的病例被要求更早复查（其中 0→1 级 1 张 —— 两级都是绿色，
# 只是复查文案微调，患者无感；其余 7 张紧急度确实上调）。
# 比例约 1:1，考虑到「漏转诊」的代价远高于「多复查一次」，这个交换是划算的。
#
# 更重要的一个实测结论：这个机制**抓不住「自信地错」**——
# 13 张真实 3 级被判 2 级的样本里，只有 1 张是「犹豫的」（概率差 < 0.12），
# 其余 12 张模型给 2 级的概率远高于 3 级。想真正改善 3 级召回，
# 得靠病灶级标注训练，不是调阈值。别把这个兜底当成分级器变好了。
#
# 环境变量可调：想更保守就 BORDERLINE_GAP=0.20（救回 12 张、代价 14 张）。
BORDERLINE_GAP = float(os.environ.get("BORDERLINE_GAP", "0.12"))


def triage_fundus(level: int, confidence: float, probs: list | None = None,
                  quality: str = "可评估") -> dict:
    """根据 DR 分级返回分诊信息。

    probs 传入时启用「边界保守升级」：只调整科室/紧急度/复查时限，
    **level 与 level_name 永远保持模型原始输出**。
    报告上的分级数字必须与模型一致，改了就是造假；能保守的是行动建议，不是结论。
    """
    info = DR_LEVELS[level]
    borderline, escalated_to, gap = False, None, 1.0
    tri_info = info
    # 质量不可评估时不做边界升级：一张废图的概率分布本来就没有意义，
    # 拿它的 top1/top2 差值去推「保守就诊时限」，等于用一个噪声结论去改行动建议。
    if probs and len(probs) >= 5 and 0 <= level < 4 and quality != "不可评估":
        gap = float(probs[level]) - float(probs[level + 1])
        if gap < BORDERLINE_GAP:
            borderline, escalated_to = True, level + 1
            tri_info = DR_LEVELS[escalated_to]

    summary = DOCTOR_SUMMARY_TEMPLATE.format(
        level=level,
        name=info["name"],
        confidence=confidence,
        quality=quality,
        lesions=info["lesions"],
        department=tri_info["department"],
        advice=tri_info["advice"],
    )
    if borderline:
        summary += (f"【边界提示】模型对 {level} 级与 {escalated_to} 级的判断接近"
                    f"（概率差 {gap:.1%}），已按更保守的 {escalated_to} 级时限建议就诊。")
    # 图像质量不达标时必须写在报告里，不能只藏在字段里：
    # 一张糊图也能得到「DR 0 级」，如果不在文字上提示，读报告的人会当成结论。
    if quality == "不可评估":
        summary += "【图像质量提示】这张图片质量不足，分级结果仅供参考，强烈建议重新拍摄后再判读。"
    elif quality == "质量偏低":
        summary += "【图像质量提示】这张图片略差，分级结果可能偏差，条件允许时建议重拍。"
    return {
        "level": level,
        "level_name": info["name"],
        "department": tri_info["department"],
        "urgency": tri_info["urgency"],
        "urgency_label": tri_info["urgency_label"],
        "advice": tri_info["advice"],
        "lesions": info["lesions"],
        "red_flags": tri_info["red_flags"],
        # 纯增量字段：前端不认也不影响渲染，认了就能显示「边界病例」标注
        "borderline": borderline,
        "escalated_to": escalated_to,
        "doctor_summary": summary,
    }


# ============================================================
# 症状分诊规则引擎：关键词匹配 + 科室权重 + 疑似方向排序
# ============================================================

# 每个症状：同义表达 patterns / 科室权重 / 疑似方向（名称, 权重）/ 基础紧急度 / 医生提示
SYMPTOM_LIBRARY = [
    {
        "name": "胸痛", "patterns": ["胸痛", "胸口痛", "胸口疼", "心前区痛", "心前区疼", "心口痛", "心口疼"],
        "depts": {"心内科": 3.0},
        "suspects": [("冠心病（心绞痛）", 5), ("肋间神经痛或胸壁肌肉劳损", 2), ("胃食管反流", 2)],
        "urgency": "orange", "note": "胸痛需优先排除心血管原因",
    },
    {
        "name": "胸闷", "patterns": ["胸闷", "胸口闷", "胸口发闷", "憋闷"],
        "depts": {"心内科": 2.0, "呼吸内科": 1.0},
        "suspects": [("心律失常", 3), ("心脏神经官能症或焦虑", 2), ("冠心病早期缺血", 2)],
        "urgency": "yellow", "note": "持续性胸闷建议先完成心电图",
    },
    {
        "name": "心慌", "patterns": ["心慌", "心悸", "心跳快", "心跳重", "心砰砰"],
        "depts": {"心内科": 2.0},
        "suspects": [("心律失常（早搏 / 房颤）", 4), ("甲状腺功能亢进", 2), ("焦虑状态", 1)],
        "urgency": "yellow", "note": "伴头晕、眼前发黑需尽快就医",
    },
    {
        "name": "气短", "patterns": ["气短", "气促", "呼吸费力", "喘不上来"],
        "depts": {"呼吸内科": 2.0, "心内科": 1.5},
        "suspects": [("支气管哮喘", 3), ("心功能不全", 3), ("贫血", 1)],
        "urgency": "orange", "note": "活动后气短加重提示心肺功能下降",
    },
    {
        "name": "头晕", "patterns": ["头晕", "头发昏", "昏沉", "发晕"],
        "depts": {"神经内科": 2.0, "心内科": 1.0},
        "suspects": [("良性位置性眩晕（BPPV）", 4), ("血压异常", 3), ("贫血", 2)],
        "urgency": "yellow", "note": "晨起或体位变化时明显，多与血压、耳石有关",
    },
    {
        "name": "眩晕", "patterns": ["眩晕", "天旋地转", "旋转感"],
        "depts": {"耳鼻喉科": 2.0, "神经内科": 1.5},
        "suspects": [("良性位置性眩晕（BPPV）", 5), ("前庭神经炎", 2), ("脑供血不足", 2)],
        "urgency": "yellow", "note": "视物旋转感强烈建议完善前庭功能检查",
    },
    {
        "name": "头痛", "patterns": ["头痛", "头疼", "偏头痛"],
        "depts": {"神经内科": 2.5},
        "suspects": [("紧张性头痛", 4), ("偏头痛", 3), ("血压异常", 2)],
        "urgency": "yellow", "note": "突发剧烈头痛需立即急诊",
    },
    {
        "name": "发热", "patterns": ["发热", "发烧", "低烧", "高热", "畏寒"],
        "depts": {"发热门诊": 2.0, "呼吸内科": 1.5},
        "suspects": [("上呼吸道感染", 4), ("流行性感冒", 3), ("肺炎", 2)],
        "urgency": "orange", "note": "超过 3 天不退或高热需查血常规",
    },
    {
        "name": "咳嗽", "patterns": ["咳嗽", "干咳", "咳痰", "咳个不停"],
        "depts": {"呼吸内科": 2.5},
        "suspects": [("急性支气管炎", 4), ("上呼吸道感染", 3), ("咳嗽变异性哮喘", 2)],
        "urgency": "yellow", "note": "超过 2 周的咳嗽建议拍胸片",
    },
    {
        "name": "乏力", "patterns": ["乏力", "没力气", "浑身无力", "疲乏", "疲倦", "累得很"],
        "depts": {"全科": 1.5, "内分泌科": 1.5},
        "suspects": [("贫血", 3), ("甲状腺功能减退", 3), ("睡眠不足或压力", 2)],
        "urgency": "green", "note": "持续乏力建议查血常规与甲状腺功能",
    },
    {
        "name": "恶心", "patterns": ["恶心", "想吐", "反胃", "恶心想吐"],
        "depts": {"消化内科": 2.0},
        "suspects": [("急性胃肠炎", 3), ("功能性消化不良", 2), ("前庭或眩晕相关", 1)],
        "urgency": "green", "note": "伴头晕时需注意前庭问题",
    },
    {
        "name": "呕吐", "patterns": ["呕吐", "吐了", "吐过", "反复吐"],
        "depts": {"消化内科": 2.5},
        "suspects": [("急性胃肠炎", 4), ("食物中毒", 3), ("其他系统疾病的反射性呕吐", 1)],
        "urgency": "yellow", "note": "反复呕吐无法进水需就医防止脱水",
    },
    {
        "name": "腹痛", "patterns": ["腹痛", "肚子痛", "肚子疼", "腹部疼", "腹部痛", "肚子不适"],
        "depts": {"消化内科": 2.5, "普外科": 1.0},
        "suspects": [("急性胃肠炎", 4), ("阑尾炎", 2), ("胆囊炎 / 胆石症", 2)],
        "urgency": "orange", "note": "转移性右下腹痛需警惕阑尾炎",
    },
    {
        "name": "腹泻", "patterns": ["腹泻", "拉肚子", "拉稀", "大便次数多"],
        "depts": {"消化内科": 2.5},
        "suspects": [("急性胃肠炎", 5), ("食物中毒", 2), ("肠易激综合征", 1)],
        "urgency": "yellow", "note": "注意补水；大便带血或黏液需就医",
    },
    {
        "name": "便秘", "patterns": ["便秘", "排便困难", "大便干", "好几天没排便"],
        "depts": {"消化内科": 2.0},
        "suspects": [("功能性便秘", 4), ("肠道功能紊乱", 2), ("甲状腺功能减退", 1)],
        "urgency": "green", "note": "优先调整膳食纤维与饮水量",
    },
    {
        "name": "腹胀", "patterns": ["腹胀", "肚子胀", "腹部胀", "胀气"],
        "depts": {"消化内科": 2.0},
        "suspects": [("功能性消化不良", 3), ("肠道气体潴留", 2), ("腹水（少见）", 1)],
        "urgency": "green", "note": "短期腹胀伴体重下降需就医排查",
    },
    {
        "name": "食欲不振", "patterns": ["食欲不振", "没胃口", "不想吃东西", "纳差", "吃不下"],
        "depts": {"消化内科": 1.8},
        "suspects": [("功能性消化不良", 3), ("慢性胃炎", 2), ("情绪或压力相关", 1)],
        "urgency": "green", "note": "持续两周以上且伴消瘦需系统检查",
    },
    {
        "name": "视力模糊", "patterns": ["视力模糊", "视物模糊", "看不清", "看东西模糊"],
        "depts": {"眼科": 2.5},
        "suspects": [("屈光不正 / 视疲劳", 3), ("糖尿病视网膜病变", 2), ("白内障", 1)],
        "urgency": "yellow", "note": "有糖尿病史者优先查眼底",
    },
    {
        "name": "耳鸣", "patterns": ["耳鸣", "耳朵响", "耳朵嗡嗡"],
        "depts": {"耳鼻喉科": 2.5},
        "suspects": [("神经性耳鸣", 4), ("耵聍栓塞", 2), ("中耳炎", 1)],
        "urgency": "green", "note": "单侧耳鸣伴听力下降需尽快检查",
    },
    {
        "name": "麻木", "patterns": ["麻木", "发麻", "手脚麻", "肢体麻木", "手麻脚麻"],
        "depts": {"神经内科": 2.5},
        "suspects": [("周围神经病变", 3), ("颈椎 / 腰椎问题", 3), ("脑血管问题", 2)],
        "urgency": "yellow", "note": "突发单侧麻木是卒中信号，需立即就医",
    },
    {
        "name": "失眠", "patterns": ["失眠", "睡不着", "入睡困难", "早醒", "睡眠差"],
        "depts": {"精神心理科": 2.0, "神经内科": 1.5},
        "suspects": [("焦虑相关失眠", 4), ("睡眠习惯问题", 2), ("甲状腺功能亢进", 1)],
        "urgency": "green", "note": "超过 3 周的失眠建议专业评估",
    },
    {
        "name": "记忆力下降", "patterns": ["记忆力下降", "记性差", "健忘", "记不住事"],
        "depts": {"神经内科": 2.0},
        "suspects": [("压力与睡眠不足", 3), ("甲状腺功能异常", 2), ("需排除器质性疾病", 1)],
        "urgency": "yellow", "note": "进行性加重并伴性格改变需神经科评估",
    },
    {
        "name": "皮疹", "patterns": ["皮疹", "起疹子", "出疹", "红疹", "皮肤痒", "瘙痒"],
        "depts": {"皮肤科": 2.5},
        "suspects": [("过敏性皮炎", 4), ("湿疹", 3), ("荨麻疹", 2)],
        "urgency": "green", "note": "伴发热或快速扩散需立即就医",
    },
    {
        "name": "关节痛", "patterns": ["关节痛", "关节疼", "关节肿", "关节不适"],
        "depts": {"骨科": 2.0, "风湿免疫科": 1.5},
        "suspects": [("骨关节炎", 4), ("类风湿关节炎", 2), ("痛风", 2)],
        "urgency": "yellow", "note": "红肿热痛伴发热需查风湿指标",
    },
    {
        "name": "水肿", "patterns": ["水肿", "浮肿", "腿肿", "眼睛肿", "脚肿"],
        "depts": {"肾内科": 2.0, "心内科": 1.5},
        "suspects": [("肾源性水肿", 3), ("心源性水肿", 3), ("静脉回流障碍", 1)],
        "urgency": "orange", "note": "晨起眼睑肿先查肾，午后下肢肿先查心",
    },
    {
        "name": "体重下降", "patterns": ["体重下降", "变瘦", "消瘦", "瘦了很多", "掉体重"],
        "depts": {"内分泌科": 2.0},
        "suspects": [("甲状腺功能亢进", 3), ("糖尿病", 3), ("需排除消耗性疾病", 2)],
        "urgency": "orange", "note": "半年内体重下降超 5% 需系统检查",
    },
]

DEPT_INFO = {
    "心内科": {"system": "心血管", "exams": ["静息心电图", "心肌酶谱 + 肌钙蛋白", "动态心电图（Holter）", "心脏彩超"]},
    "呼吸内科": {"system": "呼吸", "exams": ["胸部 X 线 / CT", "肺功能检查", "血常规"]},
    "神经内科": {"system": "神经", "exams": ["体位诱发试验（Dix–Hallpike）", "早晚血压监测", "头颅 CT / MRI（有红旗信号时）"]},
    "消化内科": {"system": "消化", "exams": ["腹部 B 超", "血常规 + 便常规", "幽门螺杆菌检测"]},
    "发热门诊": {"system": "呼吸", "exams": ["血常规 + CRP", "甲 / 乙流抗原检测", "胸片"]},
    "内分泌科": {"system": "全身", "exams": ["空腹血糖 + 糖化血红蛋白", "甲状腺功能五项", "血常规"]},
    "耳鼻喉科": {"system": "神经", "exams": ["纯音测听", "前庭功能检查"]},
    "眼科": {"system": "神经", "exams": ["视力 + 散瞳眼底检查", "眼压测量"]},
    "皮肤科": {"system": "全身", "exams": ["过敏原检测", "血常规"]},
    "骨科": {"system": "全身", "exams": ["关节 X 线", "尿酸"]},
    "风湿免疫科": {"system": "全身", "exams": ["类风湿因子 + 抗 CCP", "血沉 + CRP", "关节超声"]},
    "肾内科": {"system": "全身", "exams": ["尿常规 + 肾功能", "血清白蛋白", "下肢静脉彩超"]},
    "普外科": {"system": "消化", "exams": ["腹部 CT / B 超", "血常规"]},
    "全科": {"system": "全身", "exams": ["血常规", "肝肾功能", "空腹血糖"]},
    "精神心理科": {"system": "神经", "exams": ["焦虑 / 抑郁量表评估", "睡眠监测"]},
}

RED_FLAGS_BY_SYSTEM = {
    "心血管": ["胸痛呈压榨感、伴大汗或恶心", "胸痛放射至左臂、肩背或下颌", "突发呼吸困难、口唇发紫", "晕厥、意识丧失"],
    "神经": ["突发剧烈头痛（如雷击样）", "意识模糊、言语不清", "单侧肢体无力或麻木", "视力突然下降或视野缺损"],
    "呼吸": ["呼吸困难、口唇发紫", "咯血", "胸痛伴呼吸急促", "高热不退伴脓痰"],
    "消化": ["呕血或黑便", "腹痛剧烈难忍、腹部发硬", "持续呕吐、无法进食进水", "皮肤或眼睛发黄"],
    "全身": ["高热（>39℃）持续不退", "抽搐、意识障碍", "皮疹快速扩散伴发热", "不明原因明显消瘦"],
}

# 出现这些危重表述时，紧急度直接升级为红色
URGENCY_ESCALATION_PATTERNS = [
    "剧烈", "压榨", "大汗", "冷汗", "放射到", "左臂", "下颌",
    "突发", "如雷击", "意识不清", "意识模糊", "言语不清", "偏瘫", "一侧无力",
    "呼吸困难", "喘不上气", "晕厥", "昏倒", "抽搐",
    "呕血", "咯血", "黑便", "便血", "口唇发紫",
]

URGENCY_ORDER = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
URGENCY_LABELS = {
    "red": "红色 · 立即就医 / 拨打 120",
    "orange": "橙色 · 24 小时内就诊",
    "yellow": "黄色 · 1 周内就诊",
    "green": "绿色 · 常规门诊安排",
}
ADVICE_BY_URGENCY = {
    "red": "出现任一红旗信号请立即拨打 120 或前往急诊，保持静卧，不要自行驾车或独自前往。",
    "orange": "建议 24 小时内就诊；就诊前避免剧烈活动、饮酒与情绪激动，记录症状变化以便医生判断。",
    "yellow": "建议 1 周内门诊就诊；期间规律作息、监测症状变化，若加重请提前就医。",
    "green": "可常规门诊安排；注意休息与规律饮食，观察 1–2 周末改善再就诊。",
}


def _generic_symptom_result() -> dict:
    return {
        "ok": True,
        "matched": [],
        "department": "全科",
        "secondary": "",
        "urgency": "yellow",
        "urgency_label": URGENCY_LABELS["yellow"],
        "suspects": [],
        "exams": DEPT_INFO["全科"]["exams"],
        "red_flags": RED_FLAGS_BY_SYSTEM["全身"],
        "advice": "未能识别出明确的症状关键词。建议补充症状部位、持续时间与伴随情况后再试，或直接前往全科门诊。",
        "interpretation": "本次描述中未匹配到常见症状关键词，可能是描述过于概括。可点击左侧标签或使用引导短语补充后再试一次。",
    }


def triage_symptom(text: str) -> dict:
    """症状文本 → 科室 / 紧急度 / 疑似方向 / 检查与红旗信号。"""
    matched, notes = [], []
    dept_scores: dict[str, float] = {}
    suspect_scores: dict[str, float] = {}
    urgency = "green"

    for item in SYMPTOM_LIBRARY:
        if any(p in text for p in item["patterns"]):
            matched.append(item["name"])
            notes.append(item["note"])
            for dept, w in item["depts"].items():
                dept_scores[dept] = dept_scores.get(dept, 0) + w
            for name, w in item["suspects"]:
                suspect_scores[name] = suspect_scores.get(name, 0) + w
            if URGENCY_ORDER[item["urgency"]] > URGENCY_ORDER[urgency]:
                urgency = item["urgency"]

    if not matched:
        return _generic_symptom_result()

    escalated = any(p in text for p in URGENCY_ESCALATION_PATTERNS)
    if escalated:
        urgency = "red"

    ranked = sorted(dept_scores.items(), key=lambda kv: kv[1], reverse=True)
    primary, top_score = ranked[0]
    secondary = ranked[1][0] if len(ranked) > 1 and ranked[1][1] >= 0.4 * top_score else ""

    top_suspects = sorted(suspect_scores.items(), key=lambda kv: kv[1], reverse=True)[:3]
    pool = sum(w for _, w in top_suspects)
    probs = []
    for i, (name, w) in enumerate(top_suspects):
        if i == 0:
            # 首位吸收取整误差，保证合计 100
            p = 100 - sum(round(x / pool * 100) for _, x in top_suspects[1:])
        else:
            p = round(w / pool * 100)
        probs.append({"name": name, "prob": p})

    if len(matched) == 1:
        interpretation = f"识别到症状「{matched[0]}」。{notes[0]}。"
    else:
        interpretation = (
            f"共识别到 {len(matched)} 项症状：{'、'.join(matched)}，"
            f"组合来看更倾向「{primary}」方向。{'；'.join(notes[:2])}。"
        )
    if escalated:
        interpretation = "描述中出现需要警惕的危重表述，已按红色（最高）紧急度处理。" + interpretation

    info = DEPT_INFO.get(primary, DEPT_INFO["全科"])
    return {
        "ok": True,
        "matched": matched,
        "department": primary,
        "secondary": secondary,
        "urgency": urgency,
        "urgency_label": URGENCY_LABELS[urgency],
        "escalated": escalated,
        "suspects": probs,
        "exams": info["exams"],
        "red_flags": RED_FLAGS_BY_SYSTEM[info["system"]],
        "advice": ADVICE_BY_URGENCY[urgency],
        "interpretation": interpretation,
    }
