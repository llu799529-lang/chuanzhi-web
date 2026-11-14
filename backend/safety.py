"""确定性红旗闸门（Safety Gate）：急症识别不依赖大模型。

为什么单独做这一层
------------------
医疗分诊里最贵的错误是「把急症判轻」。大模型的紧急度判断来自提示词里一句
「出现红旗症状时用红色」，它可能漏、可能被用户话术带偏、也可能在额度耗尽时
根本不在线。所以急症识别必须有一条**不经过模型**的确定性通路：

  1. 事前短路：命中「红色」急症 → 立即返回急症指引，不调模型（更快、免费、稳定）。
  2. 事后托底：未短路但命中「橙色」信号 → 模型照常出结果，之后用 `apply_floor`
     把紧急度**只升不降**地托到规则给出的下限，并把红旗写进结果。
  3. 可审计：每条规则自带 `example`，测试逐条验证；命中证据（evidence）原样返回。

识别质量上的两个刻意处理
------------------------
- **否定与既往**：「没有胸痛」「以前有过胸痛」不触发，否则会把正常人吓成急诊。
- **组合证据**：单独「胸痛」只到橙色；「胸痛 + 冷汗/放射痛/持续不缓解」才升红色。
  同理，「说话含糊」只到橙色，「突然说话含糊」才升红色。

边界声明
--------
这是**分诊提示规则**，不是诊断。宁可多提醒一次，也不漏掉一次（对「红」偏敏感、
对「橙」偏保守）；误报的代价是多看一眼提示，漏报的代价无法挽回。词表来自常见急症
的公开科普表述，上线前应由临床医生评审并补充。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

EMERGENCY = "emergency"   # → 红色：立即拨打 120 / 急诊
URGENT = "urgent"         # → 橙色：24 小时内就诊

_RANK = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
URG_TEXT = {
    "red": "红色 · 建议立即急诊就医 / 拨打 120",
    "orange": "橙色 · 建议 24 小时内就诊",
}


@dataclass(frozen=True)
class Rule:
    id: str
    label: str
    severity: str
    dept: str
    suspect: str          # 疑似方向（规则提示，不是诊断，也不是概率）
    advice: str           # 到院前的一句话处置
    signals: tuple        # 主信号：至少一个「有效命中」
    example: str          # 自检样例：必须能命中本规则
    cosignals: tuple = ()  # 共现信号：非空时必须同时有效命中
    boost: str = ""       # 命中则把 URGENT 升为 EMERGENCY
    tests: tuple = ()     # 到院后常规检查（展示用）


@dataclass(frozen=True)
class Flag:
    id: str
    label: str
    severity: str
    dept: str
    suspect: str
    advice: str
    evidence: str
    tests: tuple = ()


# ---------------------------------------------------------------- 否定 / 既往
_BREAK = "，,。.；;！!？?\n\r:：（）()"
_NEG = re.compile(
    r"(没有|没|无|未|不曾|并无|从未|否认|排除|不伴|不是|未见|不存在|并没有|没觉得|无明显|无任何)"
    r"\s*(明显|任何|特别|太|很|什么|出现|发生|过|的)*\s*$")
_HIST = re.compile(
    r"(以前|曾经|曾|去年|前年|小时候|既往|之前|上次|几年前|多年前|年前|个月前|上周|上个月|过去)"
    r"\s*(有|出现|发生|得过|患过|诊断过)?\s*(过)?\s*((一|两|几|\d+)\s*(次|回))?\s*(的)?\s*$")
_NEG_AFTER = re.compile(r"^\s*(已经|早就|都)?(没有了|没了|消失了?|缓解了|好了|好多了|不痛了|没事了)")


def _live(text: str, rx: re.Pattern):
    """返回第一个「有效命中」：不在否定词之后、不是既往史、也没有『已经好了』。"""
    for m in rx.finditer(text):
        s = m.start()
        cut = max((text.rfind(ch, 0, s) for ch in _BREAK), default=-1)
        window = text[max(cut + 1, s - 12):s]
        if _NEG.search(window) or _HIST.search(window):
            continue
        if _NEG_AFTER.match(text[m.end():m.end() + 6]):
            continue
        return m
    return None


def _c(*patterns: str) -> tuple:
    return tuple(patterns)


# ---------------------------------------------------------------- 规则表
_ACUTE = r"突然|突发|忽然|猛然|骤然|刚(刚|才)|今(天|早|晚)|\d+\s*(分钟|小时)前|一觉醒来|醒来(后|发现)"

RULES: tuple[Rule, ...] = (
    Rule("acs", "疑似急性心脏急症（胸痛伴危险征象）", EMERGENCY, "急诊科（胸痛中心）",
         "急性冠脉综合征 / 主动脉夹层等需排除",
         "停止一切活动，静坐或半卧，松开衣领；不要自行驾车去医院。",
         signals=_c(r"胸(口|骨后|前区|部)?[^，,。；;！!？?\n]{0,3}(疼|痛|闷|紧|压)", r"胸口?发(闷|紧)", r"心(口|前区)(疼|痛)"),
         cosignals=_c(r"大汗|冷汗|出汗|濒死|压榨|放射|左(肩|臂|手|上肢)|后背|下颌|牙痛|持续(不缓解|不能缓解|\d+分钟|半小时)"
                      r"|(超过|已经|持续了?)\s*\d+\s*分钟|呼吸困难|喘不|晕|眼前发黑|恶心"),
         example="我胸口疼，出了一身冷汗，还放射到左肩",
         tests=("心电图（10 分钟内）", "心肌肌钙蛋白")),
    Rule("acs_pattern", "压榨样 / 撕裂样胸背痛", EMERGENCY, "急诊科（胸痛中心）",
         "急性冠脉综合征 / 主动脉夹层等需排除",
         "停止一切活动，静坐或半卧；不要自行驾车去医院。",
         signals=_c(r"压榨(样|性|感)", r"濒死感", r"撕裂(样|般)(的)?(胸|背)痛", r"刀割(样|般)(的)?(胸|背)痛"),
         example="胸口像被压榨一样，有濒死感"),
    Rule("chest_pain", "胸痛 / 胸闷", URGENT, "心内科（必要时急诊）",
         "心血管原因需优先排除", "避免劳累与情绪激动，尽快完成心电图；症状加重或持续请直接急诊。",
         signals=_c(r"胸(口|骨后|前区|部)?[^，,。；;！!？?\n]{0,3}(疼|痛)", r"心(口|前区)(疼|痛)", r"胸闷", r"胸口?发(闷|紧)"),
         boost=r"持续.{0,6}(不缓解|不能缓解)|越来越(重|厉害)|(超过|已经)\s*\d+\s*分钟",
         example="胸口有点疼，上楼时更明显"),
    Rule("stroke", "疑似卒中（脑血管急症）", URGENT, "急诊科（卒中中心）/ 神经内科",
         "急性缺血性或出血性卒中需排除",
         "记下症状出现的准确时间（决定能否溶栓/取栓）；平卧、头偏向一侧，不要喂水喂药，不要自行驾车。",
         signals=_c(r"口角(歪|斜)|嘴(角)?歪|歪嘴",
                    r"说话[^，,。；;！!？?\n]{0,3}(不清|含糊|不利索|吐字不清)|言语(不清|含糊|障碍)|口齿不清|舌(头)?(发硬|不灵)",
                    r"(一侧|半边|单侧|左侧|右侧|左边|右边)(的)?(肢体|手脚|手臂|胳膊|腿|身体|脸|面部)?(突然)?(无力|麻木|没劲|发麻|不听使唤|瘫)",
                    r"偏瘫|半身不遂|半边身子"),
         boost=_ACUTE,
         example="我爸突然说话含糊，嘴角歪了",
         tests=("头颅 CT / MRI", "血糖", "心电图")),
    Rule("cyanosis", "口唇发紫 / 窒息 / 气道梗阻", EMERGENCY, "急诊科",
         "严重缺氧或气道梗阻", "取坐位或半坐位，保持通风；若为异物卡喉，旁人可立即实施海姆立克急救。",
         signals=_c(r"(口唇|嘴唇|指甲|脸色)(发紫|青紫|发绀)", r"发绀", r"窒息", r"气管异物", r"被(噎|呛)住"),
         example="孩子嘴唇发紫，好像被东西噎住了"),
    Rule("dyspnea", "呼吸困难", URGENT, "呼吸内科 / 急诊科",
         "心肺急症需排除", "取坐位或半坐位，松开衣领，保持通风；明显加重请立即急诊。",
         signals=_c(r"呼吸困难|喘不(上|过)气|上不来气|透不过气|憋(气|得慌)|气不够用|喘得(厉害|很)|呼吸急促"),
         boost=r"突然|突发|严重|厉害|加重|发紫|说不出话|静息|休息时|憋醒|越来越|不能平躺|端坐",
         example="夜里突然喘不上气，憋醒了"),
    Rule("bleeding_major", "大量出血 / 呕血", EMERGENCY, "急诊科",
         "急性大出血", "有明显出血处用干净纱布直接加压止血；呕血时头偏向一侧防窒息；暂时不要进食进水。",
         signals=_c(r"大出血|血流不止|止不住(血)?|大量(出血|流血|呕血|咯血|便血)|(呕|吐)血|喷血"),
         example="他突然呕血，血流不止"),
    Rule("bleeding_urgent", "便血 / 黑便 / 咯血 / 血尿", URGENT, "急诊科或相应专科",
         "出血性疾病需排查", "记录出血量与颜色，避免进食刺激性食物；出血增多或头晕心慌请立即急诊。",
         signals=_c(r"便血|黑便|柏油样|咯血|咳血|痰中带血|血尿|阴道出血"),
         boost=r"大量|不止|止不住|头晕|心慌|冷汗|越来越多",
         example="这两天解黑便，人有点乏力"),
    Rule("consciousness", "意识障碍 / 抽搐发作", EMERGENCY, "急诊科",
         "中枢神经系统或代谢急症", "让患者平卧、头偏向一侧，保持呼吸道通畅；不要往口中塞东西或灌水；记录抽搐持续时间。",
         signals=_c(r"昏迷|意识(丧失|不清|模糊)|叫不醒|不省人事|神志不清|失去意识|昏死",
                    r"(?<!眼皮)(?<!眼角)(?<!嘴角)(?<!面部)(?<!手指)(?<!肌肉)抽搐", r"癫痫发作|四肢抽动|口吐白沫|全身僵直"),
         example="孩子发烧后突然抽搐，叫不醒"),
    Rule("syncope", "晕厥 / 昏倒", URGENT, "急诊科 / 心内科 / 神经内科",
         "心源性或神经源性晕厥需排查", "平卧抬高下肢；有胸痛、心慌、头痛或反复发作请立即急诊。",
         signals=_c(r"晕厥|晕倒|昏倒|突然(倒下|倒地)|黑矇"),
         boost=r"心慌|心悸|胸痛|胸闷|头痛|抽搐|没(醒|反应)|摔伤|反复|持续|流血|不醒|醒不过来",
         example="他刚才在楼梯口晕倒了"),
    Rule("anaphylaxis", "疑似严重过敏反应", EMERGENCY, "急诊科",
         "过敏性休克 / 喉头水肿", "立即远离过敏原；如随身备有医生开具的肾上腺素自动注射笔，按说明使用；呼吸困难取坐位，否则平卧抬高下肢。",
         signals=_c(r"过敏|蜇伤|被蜂(蜇|叮)|药物反应|吃了.{0,6}(海鲜|花生|虾|坚果)"),
         cosignals=_c(r"喉(头|咙|部)?(发紧|肿|堵|水肿)|嗓子(发紧|肿|堵)|舌(头)?肿|嘴唇肿|呼吸困难|喘不|憋"
                      r"|全身.{0,4}(荨麻疹|风团|红疹|皮疹).{0,10}(头晕|晕|心慌|血压)|晕倒|休克"),
         example="吃了海鲜后嗓子发紧，喘不上气"),
    Rule("self_harm", "自伤 / 自杀风险", EMERGENCY, "精神心理科 / 急诊科",
         "心理危机",
         "请先确保所处环境安全，立刻联系身边可信任的人陪伴；紧急时拨打 120，或拨打全国统一心理援助热线 12356（如暂未开通请拨 120）。",
         signals=_c(r"自杀|轻生|不想活|想死|寻死|结束(自己的)?生命|自残|割腕|跳楼|上吊|吞(了)?(安眠药|药片)|活着没(意思|意义)|不如死了"),
         example="我真的不想活了"),
    Rule("poison_trauma", "中毒 / 严重外伤 / 意外伤害", EMERGENCY, "急诊科",
         "中毒或严重创伤", "保留可疑毒物/药物包装带到医院；不要自行催吐（除非急救中心指示）；一氧化碳中毒应开窗通风并转移到室外。",
         signals=_c(r"服毒|喝了(农药|百草枯|敌敌畏|消毒液|洗涤剂|洁厕)|误(服|食|吞)|(?<!食物)中毒|一氧化碳|煤气中毒|触电|溺水"
                    r"|严重(烧伤|外伤|烫伤)|车祸|高处(坠落|摔下)|骨头(外露|露出)|断(肢|指)|被(刺|砍|捅)伤|吞了(电池|硬币|磁铁)"),
         example="孩子误服了一把药片"),
    Rule("neonate", "新生儿 / 小月龄婴儿异常", EMERGENCY, "儿科急诊",
         "新生儿感染或其他急症", "尽快送医，途中注意保暖和呼吸；不要自行给婴儿喂退烧药。",
         signals=_c(r"新生儿|出生(不到|才)?\s*\d+\s*(天|周)|(不满|未满|不到)\s*(3|三)\s*个月|(1|2|一|两|二)\s*个月(大)?的?(宝宝|婴儿|孩子)"),
         cosignals=_c(r"发(热|烧)|高烧|拒(奶|食)|吐奶|黄疸|呼吸(急促|困难|暂停)|口唇发紫|嗜睡|抽|囟门(鼓|凹)|体温(低|不升)"),
         example="出生20天的宝宝发烧，不肯吃奶"),
    Rule("pregnancy", "孕期危险信号", EMERGENCY, "妇产科急诊",
         "先兆流产 / 胎盘早剥 / 子痫前期等需排除", "左侧卧位休息，记录出血量与胎动情况；不要自行驾车，立即前往有产科急诊的医院。",
         signals=_c(r"怀孕|孕(妇|期)|孕\s*\d+\s*(周|月)|妊娠"),
         cosignals=_c(r"阴道(出血|流血|流液)|见红|破水|剧烈(腹痛|头痛)|腹痛(剧烈|加重)|抽搐|胎动(消失|减少|明显减少)"
                      r"|头痛.{0,6}(眼花|视物)|持续呕吐"),
         example="怀孕30周，阴道出血，肚子很痛"),
    Rule("severe_headache", "突发剧烈头痛", EMERGENCY, "急诊科（神经内科）",
         "蛛网膜下腔出血等需排除", "保持安静平卧，记录症状出现时间；不要自行服用止痛药掩盖症状。",
         signals=_c(r"(突发|突然|猛然|骤然)(的)?(剧烈|严重|炸裂|爆裂|撕裂)(的)?头(痛|疼)", r"雷击(样|般)", r"炸裂(样|般)?头(痛|疼)",
                    r"一生中最(剧烈|严重|痛)的头痛", r"头(痛|疼).{0,8}(喷射状?呕吐|颈(部)?(僵硬|发硬|强直))"),
         example="突然炸裂样头痛，还呕吐"),
    Rule("headache_red", "剧烈头痛伴危险征象", EMERGENCY, "急诊科（神经内科）",
         "颅内病变需排除", "保持安静平卧，记录症状出现时间；不要自行服用止痛药掩盖症状。",
         signals=_c(r"(剧烈|严重|炸裂)头(痛|疼)", r"头(痛|疼)[^，,。；;！!？?\n]{0,6}(剧烈|严重|厉害)"),
         cosignals=_c(r"呕吐|恶心|颈(部)?(僵硬|发硬)|意识|看不清|发热|抽"),
         example="头疼得特别剧烈，一直呕吐"),
    Rule("acute_abdomen", "剧烈腹痛", URGENT, "急诊科 / 普外科",
         "急腹症需排除", "暂时禁食禁水（可能需要手术）；不要自行服用止痛药掩盖病情。",
         signals=_c(r"(剧烈|难以忍受|受不了|刀割|绞痛|撕裂)(样|般)?.{0,3}(腹痛|肚子痛|肚子疼|腹部疼痛|上腹痛|下腹痛)",
                    r"(肚子|腹部|上腹|下腹)(剧烈|难以忍受|受不了).{0,2}(疼|痛)", r"(肚子|腹部|上腹|下腹).{0,3}(绞痛|剧痛|刀割样)",
                    r"腹痛.{0,4}(剧烈|难忍|加重|越来越)", r"肚子(痛|疼)得.{0,4}(打滚|直不起|满头大汗)", r"板状腹|肚子(硬邦邦|硬得)"),
         boost=r"冷汗|发烧|发热|呕吐|便血|黑便|晕|不能动|不敢动|休克|怀孕|右下腹|板状|越来越",
         example="肚子剧烈绞痛，已经吐了两次"),
    Rule("meningitis", "发热伴颈项强直 / 瘀点瘀斑", EMERGENCY, "急诊科",
         "脑膜炎 / 败血症需排除", "立即就医，不要自行服药观察。",
         signals=_c(r"发(热|烧)|高烧"),
         cosignals=_c(r"颈(部|项)?(僵硬|发硬|强直)|脖子(僵|硬)|(紫红色|紫色)(皮疹|瘀点|瘀斑)|瘀斑|瘀点"),
         example="孩子发烧，脖子发硬，身上有紫色的瘀点"),
    Rule("diabetic_crisis", "糖尿病急症征象", EMERGENCY, "急诊科（内分泌）",
         "酮症酸中毒 / 高渗状态 / 严重低血糖",
         "高血糖危象：不要自行大量注射胰岛素或限水，立即就医；低血糖且神志清醒：先进食约 15 克含糖食物或糖水，15 分钟后复测，仍不缓解或意识不清立即拨打 120。",
         signals=_c(r"烂苹果(味|气味)", r"酮症|酮体(高|阳性)", r"深大呼吸|呼吸深快", r"低血糖.{0,6}(昏迷|休克|抽)",
                    r"血糖(太)?低.{0,6}(昏|不醒|抽|意识)", r"糖尿病.{0,10}(昏迷|意识不清)"),
         example="糖尿病患者呼吸很深很快，呼出来有烂苹果味"),
    Rule("eye_emergency", "眼科急症征象", EMERGENCY, "眼科（急诊）",
         "视网膜脱离 / 视网膜动脉阻塞 / 急性闭角型青光眼 / 眼外伤等",
         "遮盖患眼，不要揉眼、不要自行滴药；化学物质溅入眼内请立即用大量清水或生理盐水持续冲洗至少 15 分钟后就医；记下症状开始的时间。",
         signals=_c(r"(视力|眼睛|眼)(突然|骤然|急剧|一下子|忽然).{0,6}(下降|模糊|看不见|看不清|失明|变差|黑)",
                    r"突然(看不见|失明|看不清|视物不清|看东西(变形|重影|成两个))",
                    r"(一只|单侧|左|右)眼.{0,4}(突然)?(失明|看不见)",
                    r"眼前(突然)?(出现|有)?.{0,4}(黑幕|黑影|帘子|窗帘|幕布)(遮|挡|挂|落)?",
                    r"眼前.{0,6}(闪光|闪电).{0,10}(黑影|飞蚊)", r"视野(缺损|缺失|缺一块|变窄|被遮)",
                    r"(酸|碱|化学|药水|石灰|胶水|开水).{0,6}(溅|进|入|烧|灼).{0,3}眼", r"眼(外伤|球(穿通|破裂))",
                    r"眼球.{0,4}(被)?(刺|扎|砸|撞)伤", r"眼痛.{0,8}(恶心|呕吐|虹视|头痛)", r"看(灯|光).{0,4}(彩虹|虹圈|光圈)"),
         example="我右眼突然看不见了，像拉了一层黑幕",
         tests=("散瞳眼底检查", "眼压", "OCT")),
    Rule("sudden_deafness", "突发耳聋", URGENT, "耳鼻喉科",
         "突发性聋（治疗窗口期短）", "尽快（72 小时内越早越好）到耳鼻喉科就诊，不要自行观察等待。",
         signals=_c(r"突发(性)?(耳聋|听力(下降|丧失))", r"突然(听不见|听力下降)", r"一觉醒来.{0,4}听不见"),
         example="早上醒来突然听不见了，右耳"),
)

_COMPILED = {
    r.id: (tuple(re.compile(p) for p in r.signals),
           tuple(re.compile(p) for p in r.cosignals),
           re.compile(r.boost) if r.boost else None)
    for r in RULES
}

# 同一信号被强弱两条规则同时命中时，只保留强的
_SUPERSEDED_BY = {"chest_pain": ("acs", "acs_pattern"), "bleeding_urgent": ("bleeding_major", "pregnancy"),
                  "syncope": ("consciousness",), "dyspnea": ("cyanosis",), "headache_red": ("severe_headache",)}


def _eval(rule: Rule, text: str):
    sigs, cos, boost = _COMPILED[rule.id]
    hit = None
    for rx in sigs:
        hit = _live(text, rx)
        if hit:
            break
    if not hit:
        return None
    if cos:
        co = None
        for rx in cos:
            co = _live(text, rx)
            if co:
                break
        if not co:
            return None
        evidence = f"{hit.group(0)} + {co.group(0)}"
    else:
        evidence = hit.group(0)
    severity = rule.severity
    if severity == URGENT and boost is not None and _live(text, boost):
        severity = EMERGENCY
    return severity, evidence[:40]


# ---------------------------------------------------------------- 循证依据
# 每条规则对应的国内指南 / 专家共识：kb_sources.json 里已核实（high）的来源 ID，按主题对应。
# 空元组 = 暂无登记来源，如实保留、不硬凑。tests/test_safety_basis.py 校验 ID 真实存在且为高可信度。
# 依据只说明「这条规则的主题有公开指南支撑」，不代表阈值与措辞经过临床专家评审。
RULE_BASIS: dict[str, tuple[str, ...]] = {
    "acs": ("chestpain_cn_2019",), "acs_pattern": ("chestpain_cn_2019",), "chest_pain": ("chestpain_cn_2019",),
    "stroke": ("stroke_cn_2023",), "cyanosis": (), "dyspnea": ("asthma_cn_2020", "copd_cn_2021", "hf_cn_2024"),
    "bleeding_major": ("pu_cn_2022", "hemoptysis_bj_2020"),
    "bleeding_urgent": ("hemoptysis_bj_2020", "pu_cn_2022", "aub_cn_2022"),
    "consciousness": ("epilepsy_cn_2015", "fs_cn_2017"), "syncope": ("syncope_cn_2018",),
    "anaphylaxis": ("urticaria_cn_2022",), "self_harm": ("mdd_cn_2025",), "poison_trauma": (), "neonate": (),
    "pregnancy": (), "severe_headache": ("migraine_cn_2022",), "headache_red": ("migraine_cn_2022",),
    "acute_abdomen": ("ap_cn_2021", "biliary_inf_cn_2021"), "meningitis": (), "diabetic_crisis": ("dm_cn_2024",),
    "eye_emergency": ("rvo_cn_2024", "glaucoma_cn_2020", "pvd_aao_ppp"), "sudden_deafness": ("sshl_cn_2015",),
}
GLUCOSE_BASIS: tuple[str, ...] = ("dm_cn_2024",)   # 低血糖 3.9 / 3.0 mmol/L 分级与高血糖危象阈值


def basis_ids(flags) -> list[str]:
    """一组红旗命中的循证来源 ID（去重、保持顺序）。"""
    out: list[str] = []
    for f in flags or []:
        for sid in (GLUCOSE_BASIS if f.id == "glucose" else RULE_BASIS.get(f.id, ())):
            if sid not in out:
                out.append(sid)
    return out


# ---------------------------------------------------------------- 血糖数值规则
_GLU = re.compile(r"血糖[^\d。；;\n]{0,6}?(\d{1,2}(?:\.\d{1,2})?|\d{3})(?!\d)(?!\s*(?:小时|天|周|次|年|个|分钟|月))")
_GLU_SYMPTOM = re.compile(r"恶心|呕吐|嗜睡|意识|呼吸深|腹痛|烂苹果|精神(差|萎靡)")
_GLU_LOW_SYMPTOM = re.compile(r"昏|意识|抽|不醒|出冷汗|冷汗|发抖|说胡话")


def _glucose_flags(text: str) -> list[Flag]:
    out: list[Flag] = []
    for m in _GLU.finditer(text):
        s = m.start()
        cut = max((text.rfind(ch, 0, s) for ch in _BREAK), default=-1)
        if _NEG.search(text[max(cut + 1, s - 12):s]):
            continue
        v = float(m.group(1))
        if v >= 45:          # 数值过大，按 mg/dL 理解
            v = v / 18.0
        ev = m.group(0)[:30]
        if v >= 33.3:
            sev, label = EMERGENCY, "血糖极度升高（≥ 33.3 mmol/L）"
        elif v >= 16.7:
            sev = EMERGENCY if _GLU_SYMPTOM.search(text) else URGENT
            label = "血糖明显升高（≥ 16.7 mmol/L）" + ("伴危险症状" if sev == EMERGENCY else "")
        elif v <= 3.0:
            sev, label = EMERGENCY, "严重低血糖（≤ 3.0 mmol/L）"
        elif v < 3.9:
            sev = EMERGENCY if _GLU_LOW_SYMPTOM.search(text) else URGENT
            label = "低血糖（< 3.9 mmol/L）" + ("伴意识/神经症状" if sev == EMERGENCY else "")
        else:
            continue
        out.append(Flag("glucose", label, sev, "急诊科（内分泌）" if sev == EMERGENCY else "内分泌科 / 急诊科",
                        "高血糖危象或低血糖急症",
                        "高血糖：不要自行大量注射胰岛素或限水，尽快就医；低血糖且清醒：先吃约 15 克含糖食物，15 分钟后复测，仍不缓解或意识不清立即拨打 120。",
                        ev))
        break
    return out


# ---------------------------------------------------------------- 对外接口
def detect(text: str) -> list[Flag]:
    """扫描文本，返回红旗列表（急症在前）。空文本、无命中返回 []。"""
    if not text or not text.strip():
        return []
    text = text[:20000]
    found: dict[str, Flag] = {}
    for rule in RULES:
        res = _eval(rule, text)
        if res:
            sev, ev = res
            found[rule.id] = Flag(rule.id, rule.label, sev, rule.dept, rule.suspect, rule.advice, ev, rule.tests)
    for weak, strong in _SUPERSEDED_BY.items():
        if weak in found and any(s in found and found[s].severity == EMERGENCY for s in strong):
            del found[weak]
    flags = list(found.values()) + _glucose_flags(text)
    flags.sort(key=lambda f: f.severity != EMERGENCY)   # 稳定排序：急症在前
    return flags


def has_emergency(flags) -> bool:
    return any(f.severity == EMERGENCY for f in flags or [])


def floor_urgency(flags) -> str | None:
    """规则给出的紧急度下限：red / orange / None。"""
    if not flags:
        return None
    return "red" if has_emergency(flags) else "orange"


def public(flags) -> list[dict]:
    return [{"id": f.id, "label": f.label, "severity": f.severity, "evidence": f.evidence} for f in flags or []]


def prompt_note(flags) -> str:
    """给模型的提示：规则已检测到的红旗，紧急度不得低于下限。"""
    if not flags:
        return ""
    floor = "红色" if has_emergency(flags) else "橙色"
    names = "；".join(f"{f.label}（命中：{f.evidence}）" for f in flags[:4])
    return (f"【系统红旗检测（确定性规则，非模型判断）】已识别：{names}。"
            f"紧急度不得低于「{floor}」，reds 中必须包含对应红旗信号，并明确提示尽快就医。")


def apply_floor(card: dict, flags) -> dict:
    """把症状卡的紧急度「只升不降」地托到规则下限，并写入红旗与证据。幂等。"""
    if not flags or not isinstance(card, dict) or card.get("kind") not in (None, "symptom"):
        return card
    floor = floor_urgency(flags)
    cur = card.get("urgency") if card.get("urgency") in _RANK else "yellow"
    raised = _RANK[floor] > _RANK[cur]
    was_raised = bool((card.get("safety") or {}).get("raised"))   # 重复调用时保持「已被规则抬升」的事实
    if raised:
        card["urgency"] = floor
        card["urg"] = URG_TEXT[floor]
        if floor == "red":
            top = next(f for f in flags if f.severity == EMERGENCY)
            old = str(card.get("dept") or "")
            if top.dept and old and top.dept.split("（")[0] not in old:
                card["alt"] = f"待急诊评估后再转{old}" + (f"；{card['alt']}" if card.get("alt") else "")
            card["dept"] = top.dept or card.get("dept") or "急诊科"
    reds = [f"{f.label}（命中：{f.evidence}）" for f in flags]
    old_reds = [r for r in (card.get("reds") or []) if r not in reds]
    card["reds"] = (reds + old_reds)[:6]
    card["safety"] = {"gate": "rule", "floor": floor, "raised": raised or was_raised, "flags": public(flags)}
    return card


def emergency_symptom_card(query: str, flags, kb_hits: list | None = None) -> dict:
    """急症短路时直接返回的症状卡（与 `_norm_symptom` 同形，前端无需改动）。"""
    em = [f for f in flags if f.severity == EMERGENCY] or list(flags)
    top = em[0]
    card = {
        "kind": "symptom",
        "hits": [f.evidence for f in em][:4],
        "echo": f"{top.label}（红旗预警）",
        "dept": top.dept,
        "urg": URG_TEXT["red"],
        "alt": "到院前请勿自行驾车，请有人陪同；先拨打 120。",
        "suspects": [],     # 红旗规则只给「需排除的方向」，不给概率——不编造百分比
        "tests": list(top.tests) or ["到院后由急诊医生评估生命体征并安排检查"],
        "prep": ["立即拨打 120，说明症状、发生时间和所在位置", top.advice,
                 "备好身份证件、既往病历和正在服用的药物", "不要自行驾车，请家属陪同"],
        "reds": [f"{f.label}（命中：{f.evidence}）" for f in em][:6],
        "urgency": "red",
        "degraded": False,
        "source": "safety_gate",
        "safety_note": "本结果由确定性红旗规则直接生成，未调用大模型，不是诊断。",
        "safety": {"gate": "rule", "floor": "red", "raised": True, "flags": public(flags)},
    }
    if kb_hits:
        card["kb_hits"] = kb_hits
    return card


def emergency_plain(flags) -> str:
    em = [f for f in flags if f.severity == EMERGENCY] or list(flags)
    names = "、".join(f.label for f in em[:3])
    top = em[0]
    return (
        f"【红旗预警】根据你的描述，识别到需要立即处理的信号：{names}。\n"
        "请现在就做：\n"
        "1. 立即拨打 120（或请家人代为拨打），说明症状、发生时间和所在位置；\n"
        f"2. {top.advice}\n"
        "3. 不要自行驾车，请有人陪同；\n"
        "4. 备好身份证件、既往病历和正在服用的药物，方便急救人员了解情况。\n"
        f"需要排除的方向：{top.suspect}（这是提示，不是诊断）。\n"
        "本提示由内置确定性规则生成，未调用大模型；以现场急救人员和医生的判断为准。"
    )
