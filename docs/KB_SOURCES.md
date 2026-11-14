# 知识库参考依据核实报告

> 本文件由 `backend/evals/build_kb_sources.py` 根据 `backend/kb_sources.json` 自动生成，请改登记表而不是改本文件。

- 核实日期：**2026-10-26**
- 覆盖：知识库 **94 / 100** 条已标注参考依据；**6** 条没有找到可靠出处，保持空白
- 来源：登记 **92** 条，其中 high **90** 条（已写入知识库的有 89 条），medium 仅登记不写入

## 这份报告能证明什么，不能证明什么

- **方法**：联网检索（WebSearch）逐主题核实；题名须在 ≥2 个不同站点的结果中一致出现才标 high，只有 1 个站点的标 medium。web_fetch 被网络白名单拦截，所以只核实了「该文献真实存在、题名/署名/出处与检索结果一致」，没有逐句比对指南正文。
- **映射口径**：知识库条目 → 来源是主题级映射：来源只说明该主题有可对照的权威文献，不代表该条目每个疾病、每句话都被该文献覆盖；各来源的 scope/note 写明了覆盖范围。
- **能说**：登记的文献真实存在，题名、署名单位、出处与检索结果一致，每条都有可点开的证据链接。
- **不能说**：「知识库内容来自这些指南」「知识库经过指南核对」「经过医生审核」。知识库内容由项目作者整理，没有逐句比对。

- 注意：指南会更新，部分来源已有更新版（见各条 note），收录的是已核实的版本
- 注意：知识库条目内容由项目作者整理，未经临床医生评审
- 注意：没有找到可靠出处的条目留空，不编造

## 置信度

- **high**：题名与出处在 ≥2 个站点（或 1 个一手官方站点加 1 个转载站点）一致；写入知识库
- **medium**：只在 1 个站点看到；仅登记，不写入知识库，待二次核实

## 来源登记（按 id）

| id | 题名 | 署名 | 出处 | 类型 | 置信度 | 备注 / 覆盖范围 |
|---|---|---|---|---|---|---|
| `ad_cn_2020` | 中国特应性皮炎诊疗指南（2020版） | 中华医学会皮肤性病学分会免疫学组、特应性皮炎协作研究中心 | 《中华皮肤科杂志》2020;53(2):81-88 | 指南 | high | — |
| `aga_cma_derm` | 中国雄激素性秃发诊疗指南 | 中华医学会皮肤性病学分会毛发学组（张建中执笔） | 《临床皮肤科杂志》2014;43(3):182-186 | 指南 | high | 2026-10-26 更正：此前登记的出处不准确；多处引用一致为《临床皮肤科杂志》2014;43(3):182-186，不是《中华皮肤科杂志》。新版《中国雄激素性秃发诊疗指南（2023）》（毛发学组与中国康复医学会毛发疾病康复学组，《临床皮肤科杂志》2024;53(12)）仅见 PDF 与检索摘要，未核实，故仍引用 2014 版。与下一条 2019 年版是两个学会制定的不同文件 |
| `aga_cn_2019` | 中国人雄激素性脱发诊疗指南（2019） | 中国医师协会美容与整形医师分会毛发整形美容专业委员会 | 《中国美容整形外科杂志》（卷期未在检索结果中确认，故不写） | 指南 | high | 2026-10-26 二次核实：湖南药事服务网、知乎转载、meditool 指南库 PDF 均列出该题名。不同于皮肤性病学分会的版本 |
| `alopecia_areata_cn_2019` | 中国斑秃诊疗指南（2019） | 中华医学会皮肤性病学分会毛发学组 | 《临床皮肤科杂志》2020;49(2):69-72 | 指南 | high | 发表在《临床皮肤科杂志》，不是《中华皮肤科杂志》 |
| `anxiety_cn_2023` | 中国焦虑障碍防治指南（第二版） | 中华医学会精神医学分会组织编写；施慎逊、吴文源主编 | 中华医学电子音像出版社，2023年 | 指南（图书） | high | 2026-10-26 二次核实：出版社官网、书店页面、昆明医科大学馆藏页均列出第二版（2023）；第一版为人民卫生出版社 2010。是图书，无期刊卷期 |
| `ap_cn_2021` | 中国急性胰腺炎诊治指南（2021） | 中华医学会外科学分会胰腺外科学组 | 《中华外科杂志》2021;59(7):578-587 | 指南 | high | — |
| `appendicitis_cn_2020` | 中国急性阑尾炎诊疗指南（2020版） | 中华医学会外科学分会 | 《中华外科杂志》2020;58(12):889-894 | 指南 | medium | 仅在一页科普问答的参考文献列表中看到该条目，未找到指南原文页或摘要页，待二次核实；检索结果中多数“2020 阑尾炎指南”是 WSES（世界急诊外科学会）指南，不是本文件 |
| `ar_cn_2022` | 中国变应性鼻炎诊断和治疗指南（2022年，修订版） | 《中华耳鼻咽喉头颈外科杂志》编辑委员会、中华医学会耳鼻咽喉头颈外科学分会鼻科学组 | 《中华耳鼻咽喉头颈外科杂志》2022;57(2):106-129 | 指南 | high | — |
| `ascites_cn_2023` | 肝硬化腹水诊疗指南（2023年版） | 中华医学会肝病学分会 | （具体期刊卷期页码未在检索结果中确认，故不写） | 指南 | high | 修订并更名自《肝硬化腹水及相关并发症的诊疗指南》（《中华肝脏病杂志》2017;25(9):664-677）；含 31 条推荐意见 |
| `asthenopia_cn_2014` | 视疲劳诊疗专家共识（2014年） | 中华医学会眼科学分会眼视光学组 | 《中华眼视光学与视觉科学杂志》2014;16(7):385-387 | 专家共识 | high | 检索结果显示已有《中国视疲劳诊疗专家共识（2024年）》（《中华眼科杂志》2024;60(4)），仅 1 个站点提及，待补查 |
| `asthenopia_cn_2024` | 中国视疲劳诊疗专家共识（2024年） | 中华医学会眼科学分会眼视光学组、中国医师协会眼科医师分会眼视光学组 | 《中华眼科杂志》2024;60(4):322-329 | 专家共识 | high | — |
| `asthma_cn_2020` | 支气管哮喘防治指南（2020年版） | 中华医学会呼吸病学分会哮喘学组 | 《中华结核和呼吸杂志》2020;43(12):1023-1048 | 指南 | high | 仅 1 个站点的结果提到已有 2024 年版，尚未单独核实，故仍引用 2020 版；适用成人哮喘 |
| `aub_cn_2022` | 异常子宫出血诊断与治疗指南（2022更新版） | 中华医学会妇产科学分会妇科内分泌学组 | 《中华妇产科杂志》2022;57(7):481-490 | 指南 | high | 适用于育龄期非妊娠妇女；不含妊娠/产褥期、青春发育前、绝经后及非子宫来源出血 |
| `bc_screen_cn_2021` | 中国女性乳腺癌筛查与早诊早治指南（2021，北京） | 国家癌症中心（受国家卫生健康委员会疾病预防控制局委托） | 《中华肿瘤杂志》2021;43(4):357-382；同步刊于《中国肿瘤》2021;30(3):161-191 | 指南 | high | 发起方是国家癌症中心，不是中国抗癌协会 |
| `biliary_inf_cn_2021` | 急性胆道系统感染的诊断和治疗指南（2021版） | 中华医学会外科学分会胆道外科学组 | 《中华外科杂志》2021;59(6):422-429 | 指南 | high | — |
| `bk_cn_2025` | 中国细菌性角膜炎诊断与治疗专家共识（2025年） | 中国医师协会眼科医师分会眼感染学组 | 《中华眼科杂志》2025;61(11):854-860 | 专家共识 | high | 2026-10-26 二次核实：丁香园指南库（发布日期 2025-11-02）、动脉网、医药魔方解读均列出该题名与出处；只覆盖细菌性角膜炎，不覆盖结膜炎等；同组另有《中国带状疱疹病毒性角膜炎诊断和治疗专家共识（2025年）》（《中华眼科杂志》2025;61(2)），是另一份文件 |
| `bppv_cn_2017` | 良性阵发性位置性眩晕诊断和治疗指南（2017） | 中华医学会耳鼻咽喉头颈外科学分会、《中华耳鼻咽喉头颈外科杂志》编辑委员会 | 《中华耳鼻咽喉头颈外科杂志》2017;52(3):173-177 | 指南 | high | 有综述指出该指南更接近专家共识而非循证指南 |
| `cataract_cn_2023` | 中国成人白内障摘除手术指南（2023年） | 中华医学会眼科学分会白内障及屈光手术学组 | 《中华眼科杂志》2023;59(12):977-987 | 指南 | high | 是手术指南，主要覆盖手术时机与技术，不是白内障的完整诊疗指南 |
| `cervical_cn_2010` | 颈椎病诊治与康复指南（2010版） | 中国康复医学会颈椎病专业委员会 | 北京：中国康复医学会，2010（学会内部出版，无期刊卷期）；MedSci 收录日期 2010-08-01 | 指南 | high | 2026-10-26 二次核实：丁香园骨科频道有全文转载，MedSci 亦收录。较旧；检索未找到“2019 版”。较新的相关文件：《颈椎病的分型、诊断及非手术治疗专家共识（2018）》《颈椎病牵引治疗专家共识》（2020-12-30）、《中国颈椎退行性病变诊疗指南（2025版）》，均未核实 |
| `chb_cn_2022` | 慢性乙型肝炎防治指南（2022年版） | 中华医学会肝病学分会、中华医学会感染病学分会 | 《中华肝脏病杂志》2022;30(12):1309-1331 | 指南 | high | — |
| `chestpain_cn_2019` | 急性胸痛急诊诊疗专家共识 | 中华医学会急诊医学分会、中国医疗保健国际交流促进会胸痛分会 | 《中华急诊医学杂志》2019;28(4):413-420 | 专家共识 | high | 题名与期刊已由多个来源一致确认；个别列表把发布方归到中国医师协会急诊医师分会，正文写的是中华医学会急诊医学分会，按正文 |
| `ckd_sh_2022` | 慢性肾脏病早期筛查、诊断及防治指南（2022年版） | 上海市肾内科临床质量控制中心专家组 | 《中华肾脏病杂志》2022;38(5):453-464 | 指南 | high | 署名是上海市肾内科临床质量控制中心专家组，不是中华医学会肾脏病学分会；修订自 2017 年版 |
| `constip_cn_2019` | 中国慢性便秘专家共识意见（2019，广州） | 中华医学会消化病学分会胃肠动力学组、功能性胃肠病协作组 | 《中华消化杂志》2019;39(9):577-598 | 专家共识 | high | — |
| `copd_cn_2021` | 慢性阻塞性肺疾病诊治指南（2021年修订版） | 中华医学会呼吸病学分会慢性阻塞性肺疾病学组、中国医师协会呼吸医师分会慢性阻塞性肺疾病工作委员会 | 《中华结核和呼吸杂志》2021;44(3):170-205 | 指南 | high | — |
| `cough_cn_2021` | 咳嗽的诊断与治疗指南（2021） | 中华医学会呼吸病学分会哮喘学组 | 《中华结核和呼吸杂志》2022;45(1):13-46 | 指南 | high | — |
| `crs_cn_2018` | 中国慢性鼻窦炎诊断和治疗指南（2018） | 《中华耳鼻咽喉头颈外科杂志》编辑委员会鼻科组、中华医学会耳鼻咽喉头颈外科学分会鼻科学组 | 《中华耳鼻咽喉头颈外科杂志》2019;54(2):81-100 | 指南 | high | 检索结果显示已有《慢性鼻窦炎诊断和治疗指南（2024）》修订版（丁香园页面），尚未单独核实其出处，故仍引用 2018 版 |
| `cua_cn_2022` | 2022中国泌尿外科和男科疾病诊断治疗指南 | 中国泌尿外科和男科疾病诊断治疗指南编委会（主编：黄健） | 科学出版社，2022-11；黄健、张旭主编；2022-12-09 发布 | 指南（图书） | high | 目录已核实的章节：泌尿系结石诊断治疗指南（第 389 页起）、良性前列腺增生诊断治疗指南（第 433 页起）、泌尿系感染诊断治疗指南（第 636 页起）、前列腺炎诊断治疗指南（第 681 页起）。没有独立的“血尿”章节。只核实了目录，未读章节正文；每年更新电子版，全书每三年改版；检索中的“2022 CUA BPH 指南”多数是加拿大泌尿外科协会指南，不是本书 |
| `dementia_cn_2018` | 2018中国痴呆与认知障碍诊治指南（系列） | 中国痴呆与认知障碍指南写作组、中国医师协会神经内科医师分会认知障碍疾病专业委员会 | 《中华医学杂志》2018;98(13, 17)（系列分册：（一）痴呆及其分类诊断标准 98(13):965-970；（二）阿尔茨海默病诊治指南 98(13):971-977；（五）轻度认知障碍的诊断与治疗 98(17):1294-1301） | 指南 | high | 署名不是中华医学会神经病学分会 |
| `diarrhea_adult_2013` | 成人急性感染性腹泻诊疗专家共识 | 《中华传染病杂志》编辑委员会组织制定 | MedSci 标注发布时间 2013-12-01；期刊出处在检索结果中不一致（yiigle 页面标注为中华消化杂志），故不写 | 专家共识 | high | — |
| `dili_cn_2023` | 中国药物性肝损伤诊治指南（2023年版） | 中国医药生物技术协会药物性肝损伤防治技术专业委员会、中华医学会肝病学分会药物性肝病学组 | 《中华肝脏病杂志》2023;31(4):355-384 | 指南 | high | — |
| `dm_cn_2024` | 中国糖尿病防治指南（2024版） | 中华医学会糖尿病学分会 | 《中华糖尿病杂志》2025;17(1):16-139 | 指南 | high | 取代《中国2型糖尿病防治指南（2020年版）》，名称不再带“2型” |
| `dm_neuropathy_cn_2021` | 糖尿病神经病变诊治专家共识（2021年版） | 中华医学会糖尿病学分会神经并发症学组 | 《中华糖尿病杂志》2021;13(6):540-557 | 专家共识 | high | 是共识，不是“指南”；仅覆盖糖尿病相关神经病变 |
| `dr_cn_2022` | 我国糖尿病视网膜病变临床诊疗指南（2022年）——基于循证医学修订 | 中华医学会眼科学分会眼底病学组、中国医师协会眼科医师分会眼底病学组等 | 《中华眼底病杂志》2023;39(2) | 指南 | high | — |
| `dryeye_cn_2020` | 中国干眼专家共识：检查和诊断（2020年） | 亚洲干眼协会中国分会、海峡两岸医药卫生交流协会眼科学专业委员会眼表与泪液病学组、中国医师协会眼科医师分会眼表与干眼学组 | 《中华眼科杂志》2020;56(10):741-747 | 专家共识 | high | — |
| `dvt_cn_2017` | 深静脉血栓形成的诊断和治疗指南（第三版） | 中华医学会外科学分会血管外科学组 | 《中华普通外科杂志》2017;32(9):807-812 | 指南 | high | 仅 1 个站点的结果提到已有第四版，尚未单独核实，故仍引用第三版 |
| `eczema_cn_2011` | 湿疹诊疗指南（2011年） | 中华医学会皮肤性病学分会免疫学组 | 《中华皮肤科杂志》2011;44(1):5-6（张建中执笔） | 指南 | high | 2026-10-26 二次核实：期刊官网题录页与 MedSci 全文页均可见。较旧；检索显示已有《中国皮炎湿疹类疾病诊疗指南（2026版）》，仅见参考文献片段，未核实正文 |
| `epilepsy_cn_2015` | 临床诊疗指南·癫痫病分册（2015修订版） | 中华医学会编著；中国抗癫痫协会组织编写 | 人民卫生出版社，2015 | 指南（图书） | high | 检索结果中另有页面提到存在2023修订版，尚未核实 |
| `epistaxis_cn_2015` | 鼻出血诊断及治疗指南（草案） | 《中华耳鼻咽喉头颈外科杂志》编辑委员会鼻科组、中华医学会耳鼻咽喉头颈外科学分会鼻科学组 | 《中华耳鼻咽喉头颈外科杂志》2015;50(4):265-267 | 指南（草案） | high | 正式题名带“(草案)” |
| `facial_palsy_cn_2016` | 中国特发性面神经麻痹诊治指南 | 中华医学会神经病学分会、神经肌肉病学组、肌电图与临床神经电生理学组 | 《中华神经科杂志》2016;49(2) | 指南 | high | 不是2022年的《神经修复治疗临床指南》（那是另一份，发表于《神经损伤与功能重建》） |
| `fd_cn_2022` | 2022中国功能性消化不良诊治专家共识 | 中华医学会消化病学分会 | 《中华消化杂志》2023;43(7) | 专家共识 | high | 题名带“2022”，实际发表于 2023 年 7 月 |
| `fibroid_cn_2017` | 子宫肌瘤的诊治中国专家共识 | 子宫肌瘤的诊治中国专家共识专家组 | 《中华妇产科杂志》2017;52(12):793-800 | 专家共识 | high | — |
| `flu_nhc_2020` | 流行性感冒诊疗方案（2020年版） | 国家卫生健康委员会办公厅、国家中医药管理局办公室 | 国卫办医函〔2020〕893号，2020-10-27 | 诊疗方案 | high | 已被《流行性感冒诊疗方案（2025年版）》取代（见 flu_nhc_2025）；保留登记仅供追溯 |
| `flu_nhc_2025` | 流行性感冒诊疗方案（2025年版） | 国家卫生健康委员会办公厅、国家中医药管理局综合司 | 国卫办医急函〔2025〕26号，落款 2025-01-20；期刊版《中国感染控制杂志》2025;24(2):290-294 | 诊疗方案 | high | 修订自 2020 年版；检索未核实是否已有更新版本 |
| `fs_cn_2017` | 热性惊厥诊断治疗与管理专家共识（2017实用版） | 中华医学会儿科学分会神经学组 | 《中华实用儿科临床杂志》2017;32(18):1379-1382 | 专家共识 | high | — |
| `gad_pc_cn_2021` | 广泛性焦虑障碍基层诊疗指南（2021年） | — | 《中华全科医师杂志》2021 | 指南（基层） | high | — |
| `gerd_cn_2020` | 2020年中国胃食管反流病专家共识 | 中华医学会消化病学分会 | 《中华消化杂志》2020;40(10):649-663 | 专家共识 | high | — |
| `glaucoma_cn_2020` | 中国青光眼指南（2020年） | 中华医学会眼科学分会青光眼学组、中国医师协会眼科医师分会青光眼学组 | 《中华眼科杂志》2020;56(8):573-586 | 指南 | high | — |
| `gout_cn_2019` | 中国高尿酸血症与痛风诊疗指南（2019） | 中华医学会内分泌学分会 | 《中华内分泌代谢杂志》2020;36(1):1-13 | 指南 | high | 丁香园页面另列有 2024 版，尚未单独核实 |
| `hemoptysis_bj_2020` | 咯血诊治专家共识 | 北京医师协会呼吸内科专科医师分会咯血诊治专家共识编写组 | 《中国呼吸与危重监护杂志》2020;19(1):1-11 | 专家共识 | high | 不是中华医学会呼吸病学分会的文件 |
| `hemorrhoid_cn_2020` | 中国痔病诊疗指南（2020） | 中国中西医结合学会大肠肛门病专业委员会 | 《结直肠肛门外科》2020;26(5):519-533 | 指南 | high | — |
| `hernia_cn_2018` | 成人腹股沟疝诊断和治疗指南（2018年版） | 中华医学会外科学分会疝与腹壁外科学组、中国医师协会外科医师分会疝和腹壁外科医师委员会 | 《中华外科杂志》2018（检索结果中卷期有出入：一处写 56(7):495-498，DOI 却含 2018.08，故不写卷期） | 指南 | high | 检索显示已有《腹股沟疝诊疗指南（2024版）》（丁香园），尚未单独核实，故仍引用 2018 版 |
| `hf_cn_2024` | 中国心力衰竭诊断和治疗指南2024 | 中华医学会心血管病学分会心力衰竭学组、中国医师协会心力衰竭专业委员会、中华心血管病杂志编辑委员会 | 《中华心血管病杂志》2024;52(3):235-275 | 指南 | high | 取代《中国心力衰竭诊断和治疗指南2018》（《中华心血管病杂志》2018;46(10):760-789） |
| `hyperk_cn` | 高钾血症多学科管理专家共识 | 高钾血症多学科管理专家共识组 | 《中华急诊医学杂志》2026;35(7):902-907（肾医线解读文章日期 2026-07-24） | 专家共识 | medium | 2026-10-26 复核：引用格式在两次检索中一致，此前把 2022 年的同类共识报道误当成同一份。目前只有肾医线一家解读页（有两个镜像域名），所以仍为 medium；只覆盖高钾血症，低钾、低钠无对应文献。另见《中国慢性肾脏病患者血钾管理实践专家共识》（《中华肾脏病杂志》2020;36(10):781-792） |
| `hyperthyroid_cn_2022` | 中国甲状腺功能亢进症和其他原因所致甲状腺毒症诊治指南 | 中华医学会内分泌学分会、中国医师协会内分泌代谢科医师分会、中华医学会核医学分会等 | 《中华内分泌代谢杂志》2022;38(8) | 指南 | high | — |
| `hypothyroid_cn_2017` | 成人甲状腺功能减退症诊治指南 | — | 《中华内分泌代谢杂志》2017 | 指南 | high | 页码与署名单位未在检索结果中确认，故不写 |
| `ibs_cn_2020` | 2020年中国肠易激综合征专家共识意见 | 中华医学会消化病学分会胃肠功能性疾病协作组、胃肠动力学组 | 《中华消化杂志》2020;40(12):803-818 | 专家共识 | high | — |
| `icdr_2003` | Proposed international clinical diabetic retinopathy and diabetic macular edema disease severity scales | Wilkinson CP, Ferris FL III, Klein RE, et al. | Ophthalmology 2003;110(9):1677-1682 | 分级标准 | high | — |
| `ida_cn_2022` | 铁缺乏症和缺铁性贫血诊治和预防的多学科专家共识（2022年版） | 中华医学会血液学分会红细胞疾病（贫血）学组 | 《中华医学杂志》2022;102(41) | 专家共识 | high | — |
| `insomnia_cn_2023` | 中国成人失眠诊断与治疗指南（2023版） | 中华医学会神经病学分会睡眠障碍学组 | 《中华神经科杂志》2024;57(6):560-584 | 指南 | high | — |
| `lbp_disc_cn_2020` | 腰椎间盘突出症诊疗指南 | 中华医学会骨科学分会脊柱外科学组、骨科康复学组 | 《中华骨科杂志》2020;40(8):477-487 | 指南 | high | — |
| `lipid_cn_2023` | 中国血脂管理指南（2023年） | 中国血脂管理指南修订联合专家委员会 | 《中华心血管病杂志》2023;51(3):221-255 | 指南 | high | — |
| `lymphoma_nhc_2022` | 淋巴瘤诊疗指南（2022年版） | 国家卫生健康委员会（国家癌症中心组织编写；牵头专家石远凯） | 国卫办医函〔2022〕104号《肿瘤和血液病相关病种诊疗指南（2022年版）》附件14；通知日期 2022-04-03，官网 2022-04-11 发布 | 指南 | high | 只覆盖淋巴瘤；不覆盖反应性淋巴结增生、淋巴结结核等其它原因（K91 条目的其它疾病无对应文献；检索另见《浅表淋巴结结核的诊断与治疗专家共识》（2023），仅在一篇博客中看到，未核实）；2026-10-26 二次核实：国家卫健委官网通知页、健康界、人卫临床助手均列出该指南。检索另显示有《中国淋巴瘤诊疗指南（2026版）》，未核实。只覆盖淋巴瘤 |
| `mastopathy_cn_2016` | 乳腺增生症诊治专家共识 | 中华预防医学会妇女保健分会乳腺保健与乳腺疾病防治学组 | 《中国实用外科杂志》2016;36(7):759-762 | 专家共识 | high | 2026-10-26 二次核实：好大夫转载页与期刊 PDF 均列出该题名；DOI 10.7504/CJPS.ISSN1005-2208.2016.07.13；只覆盖乳腺增生症，不覆盖纤维腺瘤、乳腺癌 |
| `mdd_cn_2025` | 中国抑郁障碍防治指南（2025版） | 中华医学会精神医学分会（国家精神疾病医学中心、国家精神心理疾病临床医学研究中心联合发起） | 2025-09-12 在中华医学会精神医学分会第二十三次学术会议上发布；期刊出处未在检索结果中确认，故不写 | 指南 | high | — |
| `melanoma_nhc_2022` | 黑色素瘤诊疗指南（2022年版） | 国家卫生健康委员会（国家癌症中心） | 国卫办医函〔2022〕104号《肿瘤和血液病相关病种诊疗指南（2022年版）》附件；官网 2022-04-11 发布 | 指南 | high | 另有 CSCO《黑色素瘤诊疗指南》（2022版，人民卫生出版社；已更新至 2025 版），是不同的文件，未并入 |
| `migraine_cn_2022` | 中国偏头痛诊治指南（2022版） | 中国医师协会神经内科医师分会、中国研究型医院学会头痛与感觉障碍专业委员会 | 《中国疼痛医学杂志》2022年第12期，881-898页 | 指南 | high | 只覆盖偏头痛，不覆盖紧张型头痛、丛集性头痛 |
| `nafld_cn_2018` | 非酒精性脂肪性肝病防治指南（2018年更新版） | 中华医学会肝病学分会脂肪肝和酒精性肝病学组、中国医师协会脂肪性肝病专家委员会 | 《中华肝脏病杂志》2018;26(3):195-203 | 指南 | high | 已被《代谢相关（非酒精性）脂肪性肝病防治指南（2024年版）》更新（检索结果显示），尚未单独核实 2024 版出处，故仍引用 2018 版 |
| `oa_cn_2021` | 中国骨关节炎诊疗指南（2021年版） | 中华医学会骨科学分会关节外科学组、中国医师协会骨科医师分会骨关节炎学组、国家老年疾病临床医学研究中心（湘雅医院）、《中华骨科杂志》编辑部 | 《中华骨科杂志》2021;41(18):1291-1314 | 指南 | high | — |
| `osteoporosis_cn_2022` | 原发性骨质疏松症诊疗指南（2022） | 中华医学会骨质疏松和骨矿盐疾病分会 | 《中华骨质疏松和骨矿盐疾病杂志》2022;15(6):573-611 | 指南 | high | — |
| `pct_cn_2012` | 降钙素原（PCT）急诊临床应用的专家共识 | 降钙素原急诊临床应用专家共识组 | 《中华急诊医学杂志》2012;21（检索结果仅给出年月卷，页码未确认） | 专家共识 | high | 较旧；只覆盖降钙素原，不覆盖 CRP 等其他炎症标志物 |
| `perio_health_cn_2020` | 维护牙周健康的中国口腔医学多学科专家共识（第一版） | 中华口腔医学会（牙周病学、牙体牙髓病学、口腔修复学、全科口腔医学、口腔正畸、口腔种植等专业委员会） | 团体标准 T/CHSA 001—2020，2021-01-01 实施；刊于《中华口腔医学杂志》 | 专家共识/团体标准 | high | — |
| `pid_cn_2019` | 盆腔炎症性疾病诊治规范（2019修订版） | 中华医学会妇产科学分会感染性疾病协作组 | 《中华妇产科杂志》2019;54(7):433-437 | 诊治规范/专家共识 | high | — |
| `pu_cn_2022` | 消化性溃疡诊断与治疗共识意见（2022年，上海） | 中华消化杂志编辑委员会 | 《中华消化杂志》2023;43(3):176-192 | 专家共识 | high | 署名为杂志编委会而非学会；不存在“2022年，北京”版 |
| `pvd_aao_ppp` | 眼科临床指南 Preferred Practice Pattern：后玻璃体脱离、视网膜裂孔和格子样变性（中文版） | 美国眼科学会（AAO）编（2012 秋）；中华医学会眼科学分会第二次编译（2012-12，编译者赵家良） | AAO 官网 PDF；英文最新版：Kim SJ 等，Ophthalmology 2025;132(4):P163-P196（PMID 39918519） | 指南（国外） | high | 2026-10-26 二次核实：AAO 官网中文版与中文摘要页均可见，英文版 2019、2025 年有更新；未找到更新版的中文译本，故引用 2012 中文版 |
| `ra_cn_2018` | 2018中国类风湿关节炎诊疗指南 | 中华医学会风湿病学分会 | 《中华内科杂志》2018;57(4):242-251 | 指南 | high | — |
| `rau_cn_2012` | 复发性阿弗他溃疡诊疗指南（试行） | 中华口腔医学会口腔黏膜病专业委员会、中西医结合专业委员会 | 《中华口腔医学杂志》2012;47(7):402-404 | 指南（试行） | high | 2026-10-26 二次核实：万方、湖南药事服务网、中华医学知识库均列出该题名与《中华口腔医学杂志》2012;47(7):402-404；同期另有解读文章（2012;47(7):408-409）。较旧；检索未发现 2012 年之后以“专家共识”名义发表的 RAU 诊疗共识 |
| `rvo_cn_2024` | 中国视网膜静脉阻塞临床诊疗路径专家共识 | 中华医学会眼科学分会眼底病学组、中国医师协会眼科医师分会眼底病专业委员会 | 《中华眼底病杂志》2024;40(3):175-185 | 专家共识 | high | — |
| `severe_perio_cn_2017` | 重度牙周炎诊断标准及特殊人群牙周病治疗原则的中国专家共识 | 中华口腔医学会牙周病学专业委员会 | 《中华口腔医学杂志》2017;52(2):67-71 | 专家共识 | high | — |
| `sshl_cn_2015` | 突发性聋诊断和治疗指南（2015） | 《中华耳鼻咽喉头颈外科杂志》编辑委员会、中华医学会耳鼻咽喉头颈外科学分会 | 《中华耳鼻咽喉头颈外科杂志》2015;50(6):443-447 | 指南 | high | 2026-10-26 二次核实：杂志官网专题页与 MedSci 均列出该题名与页码。检索另显示 2026 年已有《突发性聋诊断和治疗指南（2026实践版/解读版）》，尚未核实，故仍引用 2015 版 |
| `stroke_cn_2023` | 中国急性缺血性卒中诊治指南2023 | 中华医学会神经病学分会、中华医学会神经病学分会脑血管病学组 | 《中华神经科杂志》2024;57(6):523-559 | 指南 | high | — |
| `syncope_cn_2018` | 晕厥诊断与治疗中国专家共识（2018） | 中华心血管病杂志编辑委员会、中国生物医学工程学会心律分会等 | 《中华心血管病杂志》2019;47(2):96-107 | 专家共识 | high | — |
| `thyroid_nodule_cn_2023` | 甲状腺结节和分化型甲状腺癌诊治指南（第二版） | 中华医学会内分泌学分会等（含外科学分会甲状腺及代谢外科学组、核医学分会、超声医学分会、中国抗癌协会头颈肿瘤专业委员会等） | 《中华内分泌代谢杂志》2023;39(3):181-226 | 指南 | high | — |
| `tmd_splint_2025` | 咬合板治疗颞下颌关节紊乱病专家共识（T/CHSA 104—2025） | 中华口腔医学会颞下颌关节病学及殆学专业委员会（团体标准） | T/CHSA 104—2025（中华口腔医学会官网 PDF） | 专家共识/团体标准 | high | 仅涉及咬合板治疗；没有找到磨牙症诊断/分型的专门共识 |
| `tumor_marker_cn_2012` | 肿瘤标志物的临床应用建议 | 中华医学会检验分会、卫生部临床检验中心、《中华检验医学杂志》编辑委员会 | 《中华检验医学杂志》2012;35(2):103-116 | 专家建议 | high | 较旧；只核实了题名与出处，未读原文。要点（不提倡对无症状人群普查、联合检测等）来自二手科普，不在此引用 |
| `tumor_marker_wst459` | WS/T 459—2018 常用血清肿瘤标志物检测的临床应用和质量管理 | 中华人民共和国国家卫生健康委员会（卫生行业标准） | WS/T 459—2018（国家卫健委官网原文 PDF） | 行业标准 | high | — |
| `uri_pc_cn_2018` | 急性上呼吸道感染基层诊疗指南（2018年） | 中华医学会、中华医学会杂志社、中华医学会全科医学分会、中华医学会呼吸病学分会感染学组等 | 《中华全科医师杂志》2019;18(5):422-426 | 指南（基层） | high | — |
| `urine_sediment_cn_2021` | 尿液检验有形成分名称与结果报告专家共识 | 中华医学会检验医学分会血液学与体液学学组 | 《中华检验医学杂志》2021;44(7):574-586 | 专家共识 | high | 2026-10-26 二次核实：多个站点转载摘要与解读；被 WS/T 229—2024 引用。是名称与报告规范，不是诊断指南 |
| `urticaria_cn_2022` | 中国荨麻疹诊疗指南（2022版） | 中华医学会皮肤性病学分会荨麻疹研究中心 | 《中华皮肤科杂志》2022;55(12):1041-1049 | 指南 | high | — |
| `uti_cn_2015` | 尿路感染诊断与治疗中国专家共识（2015版）（复杂性尿路感染；尿路感染抗菌药物选择策略及特殊类型尿路感染的治疗建议） | 尿路感染诊断与治疗中国专家共识编写组 | 《中华泌尿外科杂志》2015;36(4):241-248 | 专家共识 | high | — |
| `vertigo_cn_2017` | 眩晕诊治多学科专家共识 | 中华医学会神经病学分会、中华神经科杂志编辑委员会 | 《中华神经科杂志》2017;50(11):805-812 | 专家共识 | high | — |
| `warfarin_cn_2013` | 华法林抗凝治疗的中国专家共识 | 中华医学会心血管病学分会、中国老年学学会心脑血管病专业委员会 | 《中华内科杂志》2013;52(1) | 专家共识 | high | 较旧；同批检索另见《高龄心房颤动患者抗凝治疗中国专家共识(2024)》，对 INR 目标范围的建议不同（1.6-2.5），未并入 |
| `wst229_2024` | WS/T 229—2024 尿液理学、化学和有形成分检验 | 中华人民共和国国家卫生健康委员会（卫生行业标准，代替 WS/T 229—2002） | WS/T 229—2024（国家卫健委官网原文 PDF） | 行业标准 | high | — |

## 证据链接

**ad_cn_2020**　中国特应性皮炎诊疗指南（2020版）
- <https://guide.medlive.cn/guideline/20772>
- <http://www.pifukezazhi.com/CN/10.35541/cjd.20191000>
- <https://www.medsci.cn/guideline/show_article.do?id=0ad061c0021e76cb>
- <https://www.pfizermedicalinformation.cn/clinical-guidelines/1078>

**aga_cma_derm**　中国雄激素性秃发诊疗指南
- <https://www.haodf.com/neirong/wenzhang/8523546420.html>
- <https://www.haodf.com/neirong/wenzhang/5116658867.html>
- <https://csd.cma.org.cn/contents20/39/540.html>

**aga_cn_2019**　中国人雄激素性脱发诊疗指南（2019）
- <https://www.hnysfww.com/mobile/article.php?id=3821>
- <https://zhuanlan.zhihu.com/p/464671083>
- <http://medi-guide.meditool.cn/ymtpdf/E587EDF7-FBAD-1DAB-5CC9-9EDC649ADFAB.pdf>

**alopecia_areata_cn_2019**　中国斑秃诊疗指南（2019）
- <https://www.medsci.cn/guideline/show_article.do?id=823901c0018800ed>
- <http://medi-guide.meditool.cn/ymtpdf/E9C66448-D672-C338-C2DD-E60CB2980E43.pdf>

**anxiety_cn_2023**　中国焦虑障碍防治指南（第二版）
- <https://www.cma-cmc.com.cn/cms/znygfxl/12/4617.htm>
- <https://ir.kmmu.edu.cn/Document/Detail/E80E97FB339F33930EADCB9C397BFD85.html>
- <https://www.jd.com/xinkuan/13765c673f7e277e3df3f.html>

**ap_cn_2021**　中国急性胰腺炎诊治指南（2021）
- <https://guide.medlive.cn/guideline/23725>
- <https://drugs.dxy.cn/pc/clinicalGuidelines/pk4WH63lOWuPbOnYfSdphnw>
- <https://www.icu.cn/?p=2218>

**appendicitis_cn_2020**　中国急性阑尾炎诊疗指南（2020版）
- <https://mip.mfk.com/ask/30564627.shtml>

**ar_cn_2022**　中国变应性鼻炎诊断和治疗指南（2022年，修订版）
- <https://drugs.dxy.cn/pc/clinicalGuidelines/nSUY6mepepmvFjA5osrPwUkfmng==>
- <https://med.wanfangdata.com.cn/Paper/Detail?id=PeriodicalPaper_zhebyhk202202001&dbid=WF_QK>
- <https://www.sinomed.ac.cn/article.do?ui=2022214215>

**ascites_cn_2023**　肝硬化腹水诊疗指南（2023年版）
- <https://guide.medlive.cn/guide_v2/1/29845>
- <https://news.qq.com/rain/a/20230921A07HXB00>
- <https://www.cmtopdr.com/post/detail/33ae69f4-924a-462b-af98-1fdda194fe49>

**asthenopia_cn_2014**　视疲劳诊疗专家共识（2014年）
- <http://www.cjoovs.com/CN/Y2014/V16/I7/385>
- <https://www.medsci.cn/guideline/show_article.do?id=9fb9c1c0010900aa>
- <https://med.wanfangdata.com.cn/Paper/Detail?id=PeriodicalPaper_ysgx201407001>

**asthenopia_cn_2024**　中国视疲劳诊疗专家共识（2024年）
- <https://med.wanfangdata.com.cn/Paper/Detail?id=PeriodicalPaper_zhyk202404005&dbid=WF_QK>
- <https://www.sinomed.ac.cn/article.do?ui=2024287174>
- <https://www.vbdata.cn/intelDetail/171520>
- <https://www.sohu.com/a/779060436_121124548>

**asthma_cn_2020**　支气管哮喘防治指南（2020年版）
- <https://seleguide.yiigle.com/uploads/guide_html/%E6%94%AF%E6%B0%94%E7%AE%A1%E5%93%AE%E5%96%98%E9%98%B2%E6%B2%BB%E6%8C%87%E5%8D%97%EF%BC%882020%E5%B9%B4%E7%89%88%EF%BC%89.html>
- <https://www.sinomed.ac.cn/article.do?ui=2021157350>
- <https://newdrugs.dxy.cn/pc/clinicalGuidelines/phx-gMQFeRg5miSewpAqLrw>

**aub_cn_2022**　异常子宫出血诊断与治疗指南（2022更新版）
- <https://rs.yiigle.com/CN112141202207/1412530.htm>
- <https://newdrugs.dxy.cn/pc/clinicalGuidelines/mepepmrV5RvSBMLNFjMqFqUj0PQ==>
- <https://c.m.163.com/news/a/HMED4GO805148S1B.html>

**bc_screen_cn_2021**　中国女性乳腺癌筛查与早诊早治指南（2021，北京）
- <https://studite.yiigle.com/uploads/guide_html/%E4%B8%AD%E5%9B%BD%E5%A5%B3%E6%80%A7%E4%B9%B3%E8%85%BA%E7%99%8C%E7%AD%9B%E6%9F%A5%E4%B8%8E%E6%97%A9%E8%AF%8A%E6%97%A9%E6%B2%BB%E6%8C%87%E5%8D%97(2021%EF%BC%8C%E5%8C%97%E4%BA%AC)%20-%20%E4%B8%AD%E5%8D%8E%E8%82%BF%E7%98%A4%E6%9D%82%E5%BF%97.html>
- <https://news.qq.com/rain/a/20210420A0BX1O00>
- <http://www.chinaoncology.cn/zgzl8/ch/reader/view_abstract.aspx?file_no=A202103001>
- <https://cancer.cmt.com.cn/detail/1433564.html>

**biliary_inf_cn_2021**　急性胆道系统感染的诊断和治疗指南（2021版）
- <https://guide.medlive.cn/guideline/23581>
- <https://www.sinomed.ac.cn/article.do?ui=2021416278>
- <https://drugs.dxy.cn/pc/clinicalGuidelines/yLlSII6LasqSEPT5xqYMtBQ>
- <https://www.pfizermedicalinformation.cn/clinical-guidelines/1688>

**bk_cn_2025**　中国细菌性角膜炎诊断与治疗专家共识（2025年）
- <https://drugs.dxy.cn/pc/clinicalGuidelines/p7kbbJASEWeusLhQF7-AXaA>
- <https://www.vbdata.cn/intelDetail/838372>
- <https://bydrug.pharmcube.com/news/detail/21b14a66d77c663d489a5770ef42b2fe>

**bppv_cn_2017**　良性阵发性位置性眩晕诊断和治疗指南（2017）
- <https://drugs.dxy.cn/pc/clinicalGuidelines/pfVoV03sEUpO-iErK5s-QsQ>
- <https://www.medsci.cn/guideline/show_article.do?id=839f51c001a2919c>
- <https://zhuanlan.zhihu.com/p/633759270>

**cataract_cn_2023**　中国成人白内障摘除手术指南（2023年）
- <https://drugs.dxy.cn/pc/clinicalGuidelines/OkqWT5HmepepmZKptVThIfArApg==>
- <https://med.wanfangdata.com.cn/Paper/Detail/PeriodicalPaper_zhyk202312004>
- <https://www.sinomed.ac.cn/article.do?ui=2024159605>

**cervical_cn_2010**　颈椎病诊治与康复指南（2010版）
- <http://orthop.dxy.cn/article/15105>
- <https://www.medsci.cn/guideline/show_article.do?id=f19e31c000e85a36>
- <https://www.chinagp.net/fileup/1007-9572/PDF/zx202202020.pdf>

**chb_cn_2022**　慢性乙型肝炎防治指南（2022年版）
- <https://www.cn-healthcare.com/articlewm/20230226/content-1516237.html>
- <https://www.sinomed.ac.cn/article.do?ui=2023226495>
- <https://www.lcgdbzz.org/custom/news/id/f8240ce7-2e80-46de-b95b-b07d8fda9ae9>

**chestpain_cn_2019**　急性胸痛急诊诊疗专家共识
- <https://m.medsci.cn/guideline/show_article.do?id=ac27d1c001e5817b>
- <http://www.mdeasydiagnosis.com/jishuyingyong/673.html>
- <https://csem.cma.org.cn/attach/0/5f104921b18243f98543fc5769ba58cb.pdf>

**ckd_sh_2022**　慢性肾脏病早期筛查、诊断及防治指南（2022年版）
- <https://med.wanfangdata.com.cn/Paper/Detail?id=PeriodicalPaper_zhszb98202205014&dbid=WF_QK>
- <https://drugs.dxy.cn/pc/clinicalGuidelines/v6zpTYFsplsplslFhcntK0KZSPw==>
- <https://www.zgsyz.com/zgsynk/CN/10.19538/j.nk2022090108>

**constip_cn_2019**　中国慢性便秘专家共识意见（2019，广州）
- <https://drugs.dxy.cn/pc/clinicalGuidelines/pIAoMPYZHXQhXBqQJizK2VQ>
- <https://www.sohu.com/a/353096872_652863>
- <https://www.cn-healthcare.com/articlewm/20200507/wap-content-1110744.html>

**copd_cn_2021**　慢性阻塞性肺疾病诊治指南（2021年修订版）
- <https://www.pfizermedicalinformation.cn/clinical-guidelines/2196>
- <https://www.medsci.cn/guideline/show_article.do;jsessionid=679C17B4FE72F58084D70D18B717FCC4?id=4ea261c0021e783d>
- <https://www.chinagp.net/CN/10.12114/j.issn.1007-9572.2021.01.304>

**cough_cn_2021**　咳嗽的诊断与治疗指南（2021）
- <https://www.hnysfww.com/mobile/article.php?id=3057>
- <https://www.cmtopdr.com/post/detail/c78590c6-76d0-421e-813e-55ca9a627fc5>
- <https://zhuanlan.zhihu.com/p/505516920>

**crs_cn_2018**　中国慢性鼻窦炎诊断和治疗指南（2018）
- <https://seleguide.yiigle.com/uploads/guide_html/%E4%B8%AD%E5%9B%BD%E6%85%A2%E6%80%A7%E9%BC%BB%E7%AA%A6%E7%82%8E%E8%AF%8A%E6%96%AD%E5%92%8C%E6%B2%BB%E7%96%97%E6%8C%87%E5%8D%97%EF%BC%882018%EF%BC%89.html>
- <https://www.hnysfww.com/mobile/article.php?id=971>
- <https://www.medsci.cn/guideline/show_article.do?id=8dec51c001e27183>

**cua_cn_2022**　2022中国泌尿外科和男科疾病诊断治疗指南
- <https://www.dushu.com/book/13972840/>
- <https://www.cnknowledge.com/detail/monograph?id=1595341253355114496&type=2>
- <https://book.sciencereading.cn/shop/book/Booksimple/show.do?id=BEB5E958AE8FD024FE053020B0A0A8C10000>
- <https://www.vbdata.cn/newsDetail/be6e13d477e311ed973800163e0cb09b>

**dementia_cn_2018**　2018中国痴呆与认知障碍诊治指南（系列）
- <http://commercial.dxy.cn/article/607953>
- <https://seleguide.yiigle.com/uploads/guide_html/2018%E4%B8%AD%E5%9B%BD%E7%97%B4%E5%91%86%E4%B8%8E%E8%AE%A4%E7%9F%A5%E9%9A%9C%E7%A2%8D%E8%AF%8A%E6%B2%BB%E6%8C%87%E5%8D%97(%E4%BA%94)%EF%BC%9A%E8%BD%BB%E5%BA%A6%E8%AE%A4%E7%9F%A5%E9%9A%9C%E7%A2%8D%E7%9A%84%E8%AF%8A%E6%96%AD%E4%B8%8E%E6%B2%BB%E7%96%97.html>
- <https://www.medsci.cn/guideline/show_article.do?id=ad9431c001588226>

**diarrhea_adult_2013**　成人急性感染性腹泻诊疗专家共识
- <https://www.medsci.cn/guideline/show_article.do?id=254e91c0010313cb>
- <https://91huayi.com/cme/contents/211/5938.html>
- <https://www.medtrib.cn/post/detail/b9b90906-21d7-4914-9425-4e1e44ddfb76>
- <https://master.yiigle.com/uploads/guide_html/%E6%88%90%E4%BA%BA%E6%80%A5%E6%80%A7%E6%84%9F%E6%9F%93%E6%80%A7%E8%85%B9%E6%B3%BB%E8%AF%8A%E7%96%97%E4%B8%93%E5%AE%B6%E5%85%B1%E8%AF%86.html>

**dili_cn_2023**　中国药物性肝损伤诊治指南（2023年版）
- <https://drugs.dxy.cn/pc/clinicalGuidelines/yTwPWXl6Jk2Ac65yMd0okxw>
- <https://www.pfizermedicalinformation.cn/clinical-guidelines/2544>
- <https://www.liver.org.cn/content-detail?C_ID=2305&Column_ID=undefined>

**dm_cn_2024**　中国糖尿病防治指南（2024版）
- <https://diab.cma.org.cn/cn/zhinangongshi.aspx>
- <https://guide.medlive.cn/guideline/33909>
- <https://drugs.dxy.cn/pc/clinicalGuidelines/pC7RJoNHj1YANrh50uWaVA==>

**dm_neuropathy_cn_2021**　糖尿病神经病变诊治专家共识（2021年版）
- <https://diab.cma.org.cn/cn/ncontent.aspx?oid=2674>
- <https://www.cn-healthcare.com/article/20210722/content-557597.html>
- <https://weixin.incongress.cn/zhnfbnotes.do?method=getNotesByIdLMV2&openid=o8s8YuFwipE3Vdr-lVhrU77jJOkA&notesId=41224>

**dr_cn_2022**　我国糖尿病视网膜病变临床诊疗指南（2022年）——基于循证医学修订
- <https://guide.medlive.cn/guide_v2/1/28050>
- <https://www.mdweekly.com.cn/index/article/detail?id=41757>
- <https://www.sohu.com/a/664330539_121118852>

**dryeye_cn_2020**　中国干眼专家共识：检查和诊断（2020年）
- <https://www.sinomed.ac.cn/article.do?ui=2020734597>
- <https://www.medsci.cn/guideline/show_article.do?id=cba661c00200e3f3>
- <https://www.haodf.com/neirong/wenzhang/9388810362.html>

**dvt_cn_2017**　深静脉血栓形成的诊断和治疗指南（第三版）
- <https://rs.yiigle.com/CN2021/1027505.htm>
- <https://www.medsci.cn/guideline/show_article.do?id=587ed1c001502136>
- <https://www.haodf.com/neirong/wenzhang/7661882649.html>

**eczema_cn_2011**　湿疹诊疗指南（2011年）
- <http://www.pifukezazhi.com/CN/Y2011/V44/I1/5>
- <https://www.medsci.cn/guideline/show_article.do?id=5b0ae1c000820552>

**epilepsy_cn_2015**　临床诊疗指南·癫痫病分册（2015修订版）
- <https://guide.medlive.cn/guideline/10877>
- <https://www.hnysfww.com/mobile/article.php?id=964>
- <http://books.ipmph.com/books/detail/17256.shtml>

**epistaxis_cn_2015**　鼻出血诊断及治疗指南（草案）
- <https://master.yiigle.com/uploads/guide_html/%E9%BC%BB%E5%87%BA%E8%A1%80%E8%AF%8A%E6%96%AD%E5%8F%8A%E6%B2%BB%E7%96%97%E6%8C%87%E5%8D%97(%E8%8D%89%E6%A1%88).html>
- <https://m.haodf.com/neirong/wenzhang/4457734835.html>
- <https://www.medjournals.cn/clinic/getClinicList.do?subjectId=101>

**facial_palsy_cn_2016**　中国特发性面神经麻痹诊治指南
- <https://drugs.dxy.cn/pc/clinicalGuidelines/yMBw8ikj10OmDQIw456jcOQ>
- <https://cmab.yiigle.com/uploads/guide_html/%E4%B8%AD%E5%9B%BD%E7%89%B9%E5%8F%91%E6%80%A7%E9%9D%A2%E7%A5%9E%E7%BB%8F%E9%BA%BB%E7%97%B9%E8%AF%8A%E6%B2%BB%E6%8C%87%E5%8D%97.html>
- <https://www.medsci.cn/article/show_article.do?id=255c6e146aa>

**fd_cn_2022**　2022中国功能性消化不良诊治专家共识
- <https://drugs.dxy.cn/pc/clinicalGuidelines/yHKGVwmEZo0BZMeLdYVB66A>
- <https://www.sinomed.ac.cn/article.do?ui=2023449596>
- <https://nursing.medsci.cn/guideline/show_article.do?id=ddb301c003e33535>

**fibroid_cn_2017**　子宫肌瘤的诊治中国专家共识
- <https://med.wanfangdata.com.cn/Paper/Detail?id=PeriodicalPaper_zhfck201712001&dbid=WF_QK>
- <https://www.hnysfww.com/article.php?id=1467>
- <https://www.cogonline.com/info/132067971532213705_1>
- <http://dianda.cqvip.com/Qikan/Article/Detail?id=674323733>

**flu_nhc_2020**　流行性感冒诊疗方案（2020年版）
- <https://www.gov.cn/zhengce/zhengceku/2020-11/05/content_5557639.htm>
- <https://www.cn-healthcare.com/articlewm/20201105/content-1160006.html>
- <https://www.chinapneumonia.cn/hotinfo/id/682>

**flu_nhc_2025**　流行性感冒诊疗方案（2025年版）
- <http://www.natcm.gov.cn/bangongshi/gongzuodongtai/2025-01-22/35759.html>
- <https://wsjk.ln.gov.cn/wsjk/zfxxgk/zc/gjjwj/2025012320510759292/index.shtml>
- <http://www.cem.org.cn/default/content/index/id/12732>
- <https://m.bjnews.com.cn/detail/1737546629129203.html>

**fs_cn_2017**　热性惊厥诊断治疗与管理专家共识（2017实用版）
- <https://newdrugs.dxy.cn/pc/clinicalGuidelines/pS7DC6sYbitY7MJbd4D_YYQ>
- <https://www.medsci.cn/guideline/show_article.do?id=2561c1c001516832>
- <http://pediatr.dxy.cn/article/573952>

**gad_pc_cn_2021**　广泛性焦虑障碍基层诊疗指南（2021年）
- <https://www.hnysfww.com/article.php?id=3039>
- <https://bydrug.pharmcube.com/news/detail/cf8094df2127dd24871286a286687f6b>

**gerd_cn_2020**　2020年中国胃食管反流病专家共识
- <https://www.shsma.org.cn/web/weixin/5838>
- <https://www.medsci.cn/guideline/show_article.do?id=6e1c01c002e9620d>
- <https://xuebao.hebmu.edu.cn/fileup/1007-3205/HTML/2021.08.001.shtml>

**glaucoma_cn_2020**　中国青光眼指南（2020年）
- <https://www.sinomed.ac.cn/article.do?ui=2020600727>
- <https://m.medsci.cn/guideline/show_article.do?id=bee4e1c0019e339c>
- <https://med.wanfangdata.com.cn/Paper/Detail?dbid=WF_QK&id=PeriodicalPaper_zhyk202008011>

**gout_cn_2019**　中国高尿酸血症与痛风诊疗指南（2019）
- <https://drugs.dxy.cn/pc/clinicalGuidelines/99twqQlAoOEVsgbv4iQ00g==>
- <https://www.medsci.cn/guideline/show_article.do?id=e64cb1c001911045>
- <https://seleguide.yiigle.com/uploads/guide_html/%E4%B8%AD%E5%9B%BD%E9%AB%98%E5%B0%BF%E9%85%B8%E8%A1%80%E7%97%87%E4%B8%8E%E7%97%9B%E9%A3%8E%E8%AF%8A%E7%96%97%E6%8C%87%E5%8D%97(2019).html>

**hemoptysis_bj_2020**　咯血诊治专家共识
- <https://www.hnysfww.com/article.php?id=1757>
- <https://m.medsci.cn/guideline/show_article.do?id=a2d531c0018585aa>
- <https://m.haodf.com/neirong/wenzhang/9388519792.html>

**hemorrhoid_cn_2020**　中国痔病诊疗指南（2020）
- <https://guide.medlive.cn/guide_v2/1/21984>
- <https://www.medsci.cn/guideline/show_article.do?id=27d291c002010662>
- <https://zhjzcjbdzzz.cma-cmc.com.cn/CN/abstract/abstract23244.shtml>

**hernia_cn_2018**　成人腹股沟疝诊断和治疗指南（2018年版）
- <https://cmab.yiigle.com/uploads/guide_html/%E6%88%90%E4%BA%BA%E8%85%B9%E8%82%A1%E6%B2%9F%E7%96%9D%E8%AF%8A%E6%96%AD%E5%92%8C%E6%B2%BB%E7%96%97%E6%8C%87%E5%8D%97(2018%E5%B9%B4%E7%89%88).html>
- <https://zhshfbwkzz.cma-cmc.com.cn/CN/10.3877/cma.j.issn.1674-392X.2018.04.002>
- <http://www.zpwz.net/html/2018/7/201807001.html>

**hf_cn_2024**　中国心力衰竭诊断和治疗指南2024
- <https://drugs.dxy.cn/pc/clinicalGuidelines/aMKrmepepmGXTz3IdxyXKabk7MQ==>
- <https://www.medsci.cn/article/show_article.do?id=f7f383666680>
- <https://icuguideline.com/wp-content/uploads/2024/05/%E4%B8%AD%E5%9B%BD%E5%BF%83%E5%8A%9B%E8%A1%B0%E7%AB%AD%E8%AF%8A%E6%96%AD%E5%92%8C%E6%B2%BB%E7%96%97%E6%8C%87%E5%8D%972024.pdf>

**hyperk_cn**　高钾血症多学科管理专家共识
- <https://www.nephro-online.com/index/article/detail?id=11403>
- <https://www.medtrib.cn/post/detail/377075f2-551a-4c16-9f7b-7164d57c315f>

**hyperthyroid_cn_2022**　中国甲状腺功能亢进症和其他原因所致甲状腺毒症诊治指南
- <https://drugs.dxy.cn/pc/clinicalGuidelines/pQ6MT63WkThCBU7JhV9RwSw>
- <https://www.medsci.cn/guideline/show_article.do?id=ef3ed1c003ae1596>
- <https://www.qk.sjtu.edu.cn/jscp/CN/10.16139/j.1007-9610.2023.06.05>

**hypothyroid_cn_2017**　成人甲状腺功能减退症诊治指南
- <https://guide.medlive.cn/guideline/12992>
- <https://cmab.yiigle.com/uploads/guide_html/%E6%88%90%E4%BA%BA%E7%94%B2%E7%8A%B6%E8%85%BA%E5%8A%9F%E8%83%BD%E5%87%8F%E9%80%80%E7%97%87%E8%AF%8A%E6%B2%BB%E6%8C%87%E5%8D%97.html>
- <https://www.medsci.cn/article/show_article.do?id=7d6810e21383>
- <https://news.medlive.cn/endocr/info-progress/show-126483_46.html>

**ibs_cn_2020**　2020年中国肠易激综合征专家共识意见
- <https://cmab.yiigle.com/uploads/guide_html/2020%E5%B9%B4%E4%B8%AD%E5%9B%BD%E8%82%A0%E6%98%93%E6%BF%80%E7%BB%BC%E5%90%88%E5%BE%81%E4%B8%93%E5%AE%B6%E5%85%B1%E8%AF%86%E6%84%8F%E8%A7%81.html>
- <https://www.shsma.org.cn/web/weixin/6565>
- <https://www.medsci.cn/guideline/show_article.do?ac=good&action=view_do&id=79db91c0020a330b>

**icdr_2003**　Proposed international clinical diabetic retinopathy and diabetic macular edema disease severity scales
- <https://www.semanticscholar.org/paper/Proposed-international-clinical-diabetic-and-edema-Wilkinson-Ferris/889af7970391e075cbc650efefe8cf5110585fe5>
- <https://portal.research.lu.se/en/publications/proposed-international-clinical-diabetic-retinopathy-and-diabetic/>
- <https://www.aaojournal.org/article/S0161-6420(03)00815-7/fulltext>

**ida_cn_2022**　铁缺乏症和缺铁性贫血诊治和预防的多学科专家共识（2022年版）
- <https://guide.medlive.cn/index.php/guideline/27168>
- <https://drugs.dxy.cn/pc/clinicalGuidelines/pI6V0w5B1fHj-n2DUD93Nbg>

**insomnia_cn_2023**　中国成人失眠诊断与治疗指南（2023版）
- <https://guide.medlive.cn/guide_v2/1/32110>
- <https://drugs.dxy.cn/pc/clinicalGuidelines/pD93USS4sicrW8p2srlxlqQ>
- <https://www.sinomed.ac.cn/article.do?ui=2024399025>

**lbp_disc_cn_2020**　腰椎间盘突出症诊疗指南
- <https://guide.medlive.cn/guideline/20767>
- <https://www.sinomed.ac.cn/article.do?ui=2020459688>
- <https://meeting.orthonline.com.cn/node/136703>

**lipid_cn_2023**　中国血脂管理指南（2023年）
- <https://csc.cma.org.cn/art/2023/3/28/art_619_50122.html>
- <https://guide.medlive.cn/guide_v2/1/28314>
- <https://www.sinomed.ac.cn/article.do?ui=2023196990>

**lymphoma_nhc_2022**　淋巴瘤诊疗指南（2022年版）
- <https://www.nhc.gov.cn/yzygj/c100068/202204/0c1f7d3aca0545abbeb02030ce255930.shtml>
- <https://www.cn-healthcare.com/article/20220413/content-568520.html>
- <https://ccdas.pmphai.com/appguide/toPcDetail?sessionId=&knowledgeLibPrefix=guide&id=1674371831584260097>

**mastopathy_cn_2016**　乳腺增生症诊治专家共识
- <https://m.haodf.com/neirong/wenzhang/4848599690.html>
- <http://medi-guide.meditool.cn/ymtpdf/6D12FF16-6F81-6E99-E517-CB9A4C1EF3BA.pdf>

**mdd_cn_2025**　中国抑郁障碍防治指南（2025版）
- <https://www.stdaily.com/web/gdxw/2025-09/15/content_401217.html>
- <https://www.bjad.com.cn/Html/News/Articles/4538.html>
- <http://psy.china.com.cn/2025-09/16/content_43228832.htm>

**melanoma_nhc_2022**　黑色素瘤诊疗指南（2022年版）
- <https://www.nhc.gov.cn/yzygj/c100068/202204/0c1f7d3aca0545abbeb02030ce255930/files/1732863054447_72541.pdf>
- <https://www.medsci.cn/guideline/show_article.do?id=2966c1c002a1258c>
- <https://ccdas.pmphai.com/appguide/toPcDetail?sessionId=&knowledgeLibPrefix=guide&id=1643610782354636802>

**migraine_cn_2022**　中国偏头痛诊治指南（2022版）
- <http://casp.ijournals.cn/zgttyx/article/abstract/221201>
- <https://www.medsci.cn/guideline/show_article.do?id=e50bd1c002892a6a>
- <https://www.pfizermedicalinformation.cn/clinical-guidelines/2739>

**nafld_cn_2018**　非酒精性脂肪性肝病防治指南（2018年更新版）
- <https://cmab.yiigle.com/uploads/guide_html/%E9%9D%9E%E9%85%92%E7%B2%BE%E6%80%A7%E8%84%82%E8%82%AA%E6%80%A7%E8%82%9D%E7%97%85%E9%98%B2%E6%B2%BB%E6%8C%87%E5%8D%97(2018%E6%9B%B4%E6%96%B0%E7%89%88).html>
- <https://www.lcgdbzz.com/cn/article/doi/10.3969/j.issn.1001-5256.2018.05.007>
- <https://www.zgsyz.com/zgsynk/CN/10.19538/j.nk2019030108>

**oa_cn_2021**　中国骨关节炎诊疗指南（2021年版）
- <https://med.wanfangdata.com.cn/Paper/Detail?dbid=WF_QK&id=PeriodicalPaper_zhgkzz98202118001>
- <https://www.sinomed.ac.cn/article.do?ui=2021523390>
- <https://www.cn-healthcare.com/articlewm/20220121/content-1308469.html>

**osteoporosis_cn_2022**　原发性骨质疏松症诊疗指南（2022）
- <https://guide.medlive.cn/guide_v2/1/28211>
- <https://www.chinagp.net/CN/10.12114/j.issn.1007-9572.2023.0121>
- <https://tjyxxb.ijournals.cn/tjyxxb/Article/abstract/20230601>

**pct_cn_2012**　降钙素原（PCT）急诊临床应用的专家共识
- <http://www.diyalabzjg.com/uploads/14-5.pdf>
- <https://www.cn-healthcare.com/articlewm/20240521/wap-content-1634008.html>
- <https://www.medjournals.cn/journalContribute/getContributeInfo.do?bizId=7235>

**perio_health_cn_2020**　维护牙周健康的中国口腔医学多学科专家共识（第一版）
- <https://cmab.yiigle.com/uploads/guide_html/%E7%BB%B4%E6%8A%A4%E7%89%99%E5%91%A8%E5%81%A5%E5%BA%B7%E7%9A%84%E4%B8%AD%E5%9B%BD%E5%8F%A3%E8%85%94%E5%8C%BB%E5%AD%A6%E5%A4%9A%E5%AD%A6%E7%A7%91%E4%B8%93%E5%AE%B6%E5%85%B1%E8%AF%86%EF%BC%88%E7%AC%AC%E4%B8%80%E7%89%88%EF%BC%89%20-%20%E4%B8%AD%E5%8D%8E%E5%8F%A3%E8%85%94%E5%8C%BB%E5%AD%A6%E6%9D%82%E5%BF%97.html>
- <https://m.medsci.cn/guideline/show_article.do?id=654f61c0020e8075>
- <https://www.cndent.com/wp-content/uploads/2020/12/%E7%BB%B4%E6%8A%A4%E7%89%99%E5%91%A8%E5%81%A5%E5%BA%B7%E7%9A%84%E4%B8%AD%E5%9B%BD%E5%8F%A3%E8%85%94%E5%8C%BB%E5%AD%A6%E4%B8%93%E5%AE%B6%E5%85%B1%E8%AF%86%EF%BC%88%E7%AC%AC%E4%B8%80%E7%89%88%EF%BC%89.pdf>

**pid_cn_2019**　盆腔炎症性疾病诊治规范（2019修订版）
- <https://seleguide.yiigle.com/uploads/guide_html/%E7%9B%86%E8%85%94%E7%82%8E%E7%97%87%E6%80%A7%E7%96%BE%E7%97%85%E8%AF%8A%E6%B2%BB%E8%A7%84%E8%8C%83%EF%BC%882019%E4%BF%AE%E8%AE%A2%E7%89%88%EF%BC%89.html>
- <https://www.medsci.cn/guideline/show_article.do?id=bd2a31c001e950be>
- <https://drugs.dxy.cn/pc/clinicalGuidelines/EoS0CRyjjApQS39qxplsplsRj3A==>

**pu_cn_2022**　消化性溃疡诊断与治疗共识意见（2022年，上海）
- <https://rs.yiigle.com/CN2021/1457468.htm>
- <https://www.sinomed.ac.cn/article.do?ui=2023315925>
- <https://drugs.dxy.cn/pc/clinicalGuidelines/y_asGEV8RrCo25l8Yfm10Lg>

**pvd_aao_ppp**　眼科临床指南 Preferred Practice Pattern：后玻璃体脱离、视网膜裂孔和格子样变性（中文版）
- <https://www.aao.org/asset.axd?id=a3ef2867-28f5-4715-8005-57db7e3106e6>
- <https://www.aao.org/Assets/9692ef50-d8dc-44ec-9cb8-0ac9430172ae/635261821275970000/chinese-summary-benchmarks-2012-pdf>
- <https://www.guidelinecentral.com/guideline/10643/>
- <https://m.amedeo.com/39918519>

**ra_cn_2018**　2018中国类风湿关节炎诊疗指南
- <https://guide.medlive.cn/guideline/15327>
- <https://cmab.yiigle.com/uploads/guide_html/2018%E4%B8%AD%E5%9B%BD%E7%B1%BB%E9%A3%8E%E6%B9%BF%E5%85%B3%E8%8A%82%E7%82%8E%E8%AF%8A%E7%96%97%E6%8C%87%E5%8D%97.html>
- <http://commercial.dxy.cn/article/561206>

**rau_cn_2012**　复发性阿弗他溃疡诊疗指南（试行）
- <https://med.wanfangdata.com.cn/Paper/Detail?id=PeriodicalPaper_zhkqyx201207007>
- <https://www.hnysfww.com/mobile/article.php?id=1044>
- <http://seleguide.yiigle.com/home/agent/getperinfo.html?id=3013>

**rvo_cn_2024**　中国视网膜静脉阻塞临床诊疗路径专家共识
- <https://rs.yiigle.com/CN115399202004/1501789.htm>
- <https://drugs.dxy.cn/pc/clinicalGuidelines/ppPoPWrPmdTWU0W9tDdHMig>
- <https://www.sohu.com/a/761782506_401085>

**severe_perio_cn_2017**　重度牙周炎诊断标准及特殊人群牙周病治疗原则的中国专家共识
- <https://www.sohu.com/a/191494610_352617>
- <https://www.medsci.cn/guideline/show_article.do?id=c8a451c001a83670>

**sshl_cn_2015**　突发性聋诊断和治疗指南（2015）
- <https://www.entnet.org.cn/topic/42.jspx>
- <https://www.medsci.cn/guideline/show_article.do?id=59aa91c00122064c>
- <http://medline.ceshi.yiigle.com/clinic/subjectDetail.do?subjectId=101>

**stroke_cn_2023**　中国急性缺血性卒中诊治指南2023
- <https://guide.medlive.cn/guide_v2/1/32109>
- <https://www.brainmed.com/info/detail?id=46500>
- <https://www.chinastroke.org.cn/CN/10.3969/j.issn.1673-5765.2024.08.013>

**syncope_cn_2018**　晕厥诊断与治疗中国专家共识（2018）
- <https://guide.medlive.cn/guideline/17894>
- <https://www.medsci.cn/guideline/show_article.do?id=145011c001e3a432>
- <https://www.zgsyz.com/zgsynk/CN/10.19538/j.nk2019110107>

**thyroid_nodule_cn_2023**　甲状腺结节和分化型甲状腺癌诊治指南（第二版）
- <https://guide.medlive.cn/guideline/28363>
- <https://www.hnysfww.com/mobile/article.php?id=3616>
- <https://www.medsci.cn/guideline/show_article.do?id=2d6ae1c003ae1457>

**tmd_splint_2025**　咬合板治疗颞下颌关节紊乱病专家共识（T/CHSA 104—2025）
- <https://www.cndent.com/wp-content/uploads/2025/09/TCHSA-104-2025.-%E5%92%AC%E5%90%88%E6%9D%BF%E6%B2%BB%E7%96%97%E9%A2%9E%E4%B8%8B%E9%A2%8C%E5%85%B3%E8%8A%82%E7%B4%8A%E4%B9%B1%E7%97%85%E4%B8%93%E5%AE%B6%E5%85%B1%E8%AF%86.pdf>
- <https://zhuanlan.zhihu.com/p/264467682>

**tumor_marker_cn_2012**　肿瘤标志物的临床应用建议
- <https://rs.yiigle.com/CN2021/5386.htm>
- <https://www.nhc.gov.cn/wjw/s9492/201812/d40601147aa74ccba4c16dbaa40cbe06/files/1739781512088_60187.pdf>
- <http://www.cjco.cn/cn/article/pdf/preview/10.12354/j.issn.1000-8179.2021.20211020.pdf>

**tumor_marker_wst459**　WS/T 459—2018 常用血清肿瘤标志物检测的临床应用和质量管理
- <https://www.nhc.gov.cn/wjw/s9492/201812/d40601147aa74ccba4c16dbaa40cbe06/files/1739781512088_60187.pdf>
- <https://ykxb.scu.edu.cn/cn/article/pdf/preview/10.12182/20260360301.pdf>

**uri_pc_cn_2018**　急性上呼吸道感染基层诊疗指南（2018年）
- <https://seleguide.yiigle.com/uploads/guide_html/%E6%80%A5%E6%80%A7%E4%B8%8A%E5%91%BC%E5%90%B8%E9%81%93%E6%84%9F%E6%9F%93%E5%9F%BA%E5%B1%82%E8%AF%8A%E7%96%97%E6%8C%87%E5%8D%97%EF%BC%882018%E5%B9%B4%EF%BC%89.html>
- <https://www.medsci.cn/guideline/show_article.do?id=122901c001ea9356>
- <https://www.sohu.com/a/318816859_99895572>

**urine_sediment_cn_2021**　尿液检验有形成分名称与结果报告专家共识
- <https://www.muhn.edu.cn/ecmd/info/1471/10634.htm>
- <https://www.ivdchina.org/cclabd/show-1694.html>
- <http://weixin.incongress.cn/zhjyyxnotes.do?method=getNotesByIdLMV2&openid=oz2KN5oMion-M0QKzYabQRVX8_tw&notesId=41383>

**urticaria_cn_2022**　中国荨麻疹诊疗指南（2022版）
- <http://www.pifukezazhi.com/CN/10.35541/cjd.20220609>
- <https://guide.medlive.cn/guide_v2/1/27627>
- <https://drugs.dxy.cn/pc/clinicalGuidelines/vV11761ObRi82KWhQ4Pd0Q==>

**uti_cn_2015**　尿路感染诊断与治疗中国专家共识（2015版）（复杂性尿路感染；尿路感染抗菌药物选择策略及特殊类型尿路感染的治疗建议）
- <https://med.wanfangdata.com.cn/Paper/Detail/PeriodicalPaper_zhmnwk201504001>
- <https://commercial.dxy.cn/article/145647>
- <https://www.hnysfww.com/mobile/article.php?id=1228>

**vertigo_cn_2017**　眩晕诊治多学科专家共识
- <https://www.medsci.cn/guideline/show_article.do?id=8e9571c001521995>
- <https://med.wanfangdata.com.cn/Paper/Detail?id=PeriodicalPaper_zhsjk201711002>
- <http://m.neurologyclub.org/nd.jsp?id=778>

**warfarin_cn_2013**　华法林抗凝治疗的中国专家共识
- <https://cmab.yiigle.com/uploads/guide_html/%E5%8D%8E%E6%B3%95%E6%9E%97%E6%8A%97%E5%87%9D%E6%B2%BB%E7%96%97%E7%9A%84%E4%B8%AD%E5%9B%BD%E4%B8%93%E5%AE%B6%E5%85%B1%E8%AF%86.html>
- <https://www.cn-healthcare.com/articlewm/20220927/content-1442007.html>
- <https://www.haodf.com/neirong/wenzhang/894783214.html>
- <https://www.sohu.com/a/272486570_170124>

**wst229_2024**　WS/T 229—2024 尿液理学、化学和有形成分检验
- <https://www.nhc.gov.cn/fzs/c100048/202407/758b8a012f4748c9b23ee48d22d0a79a/files/1733821990822_43163.pdf>
- <https://zhlcsysgldzzz.cma-cmc.com.cn/CN/10.3877/cma.j.issn.2095-5820.2026.01.010>

## 知识库条目 → 来源

「条目内的疾病」列出该条目的前 4 个疾病，方便对照：来源只覆盖其中一部分时，以来源的 scope / note 为准。

| 条目 | 主题 | 条目内的疾病 | 来源（high） | 未写入的 medium 来源 |
|---|---|---|---|---|
| K01 | 胸痛 · 胸闷 · 心悸 | 稳定型心绞痛、急性冠脉综合征、心律失常 | `chestpain_cn_2019` | — |
| K02 | 头晕 · 眩晕 | 良性阵发性位置性眩晕（耳石症）、后循环缺血、前庭性偏头痛 | `bppv_cn_2017`、`vertigo_cn_2017` | — |
| K03 | 头痛 | 紧张型头痛、偏头痛、丛集性头痛 | `migraine_cn_2022` | — |
| K04 | 恶心 · 呕吐 | 急性胃炎、胃食管反流、功能性消化不良 | `fd_cn_2022`、`gerd_cn_2020` | — |
| K05 | 腹痛 | 急性胃肠炎、急性阑尾炎、胆囊炎 / 胆石症 | `biliary_inf_cn_2021`、`diarrhea_adult_2013` | — |
| K06 | 腹泻 | 急性感染性腹泻、肠易激综合征、炎症性肠病 | `ibs_cn_2020`、`diarrhea_adult_2013` | — |
| K07 | 咳嗽 · 咳痰 | 急性支气管炎、肺炎、咳嗽变异性哮喘 | `cough_cn_2021`、`asthma_cn_2020` | — |
| K08 | 发热 | 急性上呼吸道感染、流行性感冒、不明原因发热 | `uri_pc_cn_2018`、`flu_nhc_2025` | — |
| K09 | 呼吸困难 · 气促 | 哮喘急性发作、慢阻肺急性加重、心功能不全 | `asthma_cn_2020`、`copd_cn_2021`、`hf_cn_2024` | — |
| K10 | 鼻部症状 | 过敏性鼻炎、急性鼻窦炎、普通感冒 | `ar_cn_2022`、`crs_cn_2018`、`uri_pc_cn_2018` | — |
| K11 | 咽喉症状 | 急性咽炎 / 扁桃体炎、急性会厌炎、反流性咽喉炎 | `uri_pc_cn_2018` | — |
| K12 | 耳部症状 | 突发性耳聋、分泌性中耳炎、神经性耳鸣 | `sshl_cn_2015` | — |
| K13 | 视力下降 · 视物异常 | 视网膜静脉阻塞、孔源性视网膜脱离、糖尿病视网膜病变 | `rvo_cn_2024`、`dr_cn_2022` | — |
| K14 | 眼红 · 眼痛 · 眼干 | 急性结膜炎、干眼症、角膜炎 | `dryeye_cn_2020`、`bk_cn_2025` | — |
| K15 | 皮疹 · 瘙痒 | 荨麻疹、湿疹、药疹、接触性皮炎 | `urticaria_cn_2022`、`ad_cn_2020`、`eczema_cn_2011` | — |
| K16 | 关节痛 | 骨关节炎、类风湿关节炎、痛风性关节炎、痛风 | `oa_cn_2021`、`gout_cn_2019`、`ra_cn_2018` | — |
| K17 | 腰背痛 | 腰肌劳损、腰椎间盘突出、骨质疏松压缩骨折 | `lbp_disc_cn_2020`、`osteoporosis_cn_2022` | — |
| K18 | 排尿异常 | 尿路感染、尿路结石、前列腺增生 | `uti_cn_2015`、`cua_cn_2022` | — |
| K19 | 多饮多尿 · 体重下降 | 糖尿病、甲状腺功能亢进、尿崩症 | `dm_cn_2024` | — |
| K20 | 乏力 · 贫血 · 出血倾向 | 缺铁性贫血、血小板减少症、再生障碍性贫血 | `ida_cn_2022` | — |
| K21 | 失眠 · 焦虑 · 情绪低落 | 焦虑状态、抑郁状态、失眠症 | `gad_pc_cn_2021`、`insomnia_cn_2023`、`mdd_cn_2025`、`anxiety_cn_2023` | — |
| K22 | 牙痛 · 牙龈出血 | 龋病 / 牙髓炎、智齿冠周炎、牙周炎 | `severe_perio_cn_2017`、`perio_health_cn_2020` | — |
| K23 | 呕血 · 便血 · 黑便 | 消化性溃疡出血、痔疮、下消化道出血 | `pu_cn_2022`、`hemorrhoid_cn_2020` | — |
| K24 | 卒中预警 · 肢体无力 · 口角歪斜 | 急性脑卒中、短暂性脑缺血发作（TIA）、脑出血 | `stroke_cn_2023` | — |
| K25 | 甲状腺相关 · 手抖 · 怕热怕冷 | 甲状腺功能亢进、甲状腺功能减退、甲状腺结节 | `hyperthyroid_cn_2022`、`hypothyroid_cn_2017`、`thyroid_nodule_cn_2023` | — |
| K26 | 月经异常 · 女性下腹痛 | 月经失调、盆腔炎、子宫肌瘤 | `pid_cn_2019`、`aub_cn_2022`、`fibroid_cn_2017` | — |
| K27 | 儿童发热 · 惊厥 | 小儿急性上呼吸道感染、小儿腹泻病、手足口病 | `fs_cn_2017` | — |
| K28 | 反酸 · 烧心 · 腹胀 | 胃食管反流病、功能性消化不良、消化性溃疡 | `gerd_cn_2020`、`fd_cn_2022` | — |
| K29 | 血糖相关 | 糖尿病、糖耐量异常、低血糖 | `dm_cn_2024` | — |
| K30 | 血脂相关 | 高 LDL-C 血症、高甘油三酯血症、混合型高脂血症 | `lipid_cn_2023` | — |
| K31 | 肝功能 | 药物性肝损伤、脂肪肝、病毒性肝炎 | `dili_cn_2023`、`nafld_cn_2018`、`chb_cn_2022`、`ascites_cn_2023` | — |
| K32 | 肾功能 | 慢性肾脏病、糖尿病肾病、高尿酸血症 | `gout_cn_2019`、`ckd_sh_2022`、`dm_cn_2024` | — |
| K33 | 血常规 | 贫血、白细胞增多、血小板减少 | `ida_cn_2022` | — |
| K34 | 电解质 | 高钾血症、低钾血症、低钠血症 | **（无）** | `hyperk_cn` |
| K35 | 凝血 | 高凝状态、凝血障碍、华法林过量 | `warfarin_cn_2013` | — |
| K36 | 甲功 | 甲状腺功能亢进、甲状腺功能减退、桥本甲状腺炎 | `hyperthyroid_cn_2022`、`hypothyroid_cn_2017` | — |
| K37 | 炎症标志 | 细菌感染、自身免疫病活动、慢性炎症 | `pct_cn_2012` | — |
| K38 | 肿瘤标志 | AFP 升高、CEA 升高、PSA 升高 | `tumor_marker_cn_2012`、`tumor_marker_wst459` | — |
| K39 | 尿常规 | 泌尿系感染、蛋白尿、糖尿 | `ckd_sh_2022`、`urine_sediment_cn_2021`、`uti_cn_2015`、`wst229_2024` | — |
| K40 | 糖尿病视网膜病变 · 无明显病变 | 无明显 DR | `dr_cn_2022`、`icdr_2003` | — |
| K41 | 糖尿病视网膜病变 · 轻度 | 轻度非增殖期 DR | `dr_cn_2022`、`icdr_2003` | — |
| K42 | 糖尿病视网膜病变 · 中度 | 中度非增殖期 DR | `dr_cn_2022`、`icdr_2003` | — |
| K43 | 糖尿病视网膜病变 · 重度 | 重度非增殖期 DR | `dr_cn_2022`、`icdr_2003` | — |
| K44 | 糖尿病视网膜病变 · 增殖期 | 增殖期 DR | `dr_cn_2022`、`icdr_2003` | — |
| K45 | 白内障 | 老年性白内障 | `cataract_cn_2023` | — |
| K46 | 青光眼 | 原发性开角型青光眼、急性闭角型青光眼 | `glaucoma_cn_2020` | — |
| K47 | 干眼症 | 干眼症 | `dryeye_cn_2020` | — |
| K48 | 视疲劳 | 视疲劳、屈光不正未矫正 | `asthenopia_cn_2014`、`asthenopia_cn_2024`、`dryeye_cn_2020` | — |
| K49 | 耳鸣 · 听力下降 | 突发性耳聋、神经性耳鸣、耵聍栓塞 | `sshl_cn_2015` | — |
| K50 | 咽痛 · 咽部不适 | 急性咽炎/扁桃体炎、扁桃体周围脓肿 | `uri_pc_cn_2018` | — |
| K51 | 鼻塞 · 流涕 | 过敏性鼻炎、鼻窦炎 | `ar_cn_2022`、`crs_cn_2018`、`uri_pc_cn_2018` | — |
| K52 | 尿频 · 尿急 · 尿痛 | 尿路感染、前列腺增生、泌尿系结石 | `uti_cn_2015`、`cua_cn_2022` | — |
| K53 | 甲状腺功能亢进 | Graves病、甲亢性心脏病 | `hyperthyroid_cn_2022` | — |
| K54 | 甲状腺功能减退 | 桥本甲状腺炎、甲减性心脏病 | `hypothyroid_cn_2017` | — |
| K57 | 失眠 | 原发性失眠、焦虑相关失眠、抑郁相关失眠 | `insomnia_cn_2023` | — |
| K58 | 贫血 | 缺铁性贫血、巨幼细胞性贫血、慢性病贫血 | `ida_cn_2022` | — |
| K59 | 水肿 | 肾源性水肿、心源性水肿、单侧下肢肿胀 | `ckd_sh_2022`、`hf_cn_2024` | — |
| K60 | 体重下降 | 甲状腺功能亢进、糖尿病、消耗性疾病 | `dm_cn_2024`、`hyperthyroid_cn_2022` | — |
| K55 | 记忆力下降 · 认知减退 | 轻度认知障碍、阿尔茨海默病、血管性认知障碍 | `dementia_cn_2018` | — |
| K56 | 便秘 | 功能性便秘、肠易激综合征（便秘型）、药物性便秘 | `constip_cn_2019`、`ibs_cn_2020` | — |
| K61 | 体位性头晕 · 晕厥前兆 | 体位性低血压、血管迷走性晕厥、心源性晕厥 | `syncope_cn_2018` | — |
| K62 | 脱发 · 掉发 | 雄激素性脱发、休止期脱发、斑秃 | `alopecia_areata_cn_2019`、`aga_cma_derm`、`aga_cn_2019` | — |
| K63 | 颈肩痛 · 颈部僵硬 | 颈型颈椎病、肌筋膜疼痛综合征、高血压伴颈项强直 | `cervical_cn_2010` | — |
| K64 | 皮肤干燥 · 脱屑 | 皮肤干燥症、乏脂性湿疹、甲状腺功能减退性皮损 | `ad_cn_2020` | — |
| K65 | 飞蚊症 · 眼前黑影 | 生理性飞蚊症、玻璃体后脱离、视网膜裂孔 / 脱离 | `pvd_aao_ppp` | — |
| K66 | 疝 · 腹股沟包块 | 腹股沟疝、股疝、精索鞘膜积液 | `hernia_cn_2018` | — |
| K67 | 肌肉抽筋 · 腿抽筋 | 夜间腿部肌肉痉挛、低钙 / 电解质紊乱、下肢动脉供血不足 | **（无）** | — |
| K68 | 磨牙 · 夜间咬牙 | 睡眠期磨牙症、颞下颌关节紊乱、焦虑相关的紧咬 | `tmd_splint_2025` | — |
| K69 | 色素痣 · 皮肤肿物 | 良性色素痣、黑色素瘤、脂溢性角化 | `melanoma_nhc_2022` | — |
| K70 | 儿童皮疹 · 儿童皮肤问题 | 幼儿急疹、病毒疹、过敏性皮疹 | `ad_cn_2020` | — |
| K71 | 疲劳 · 活动耐力下降 | 贫血、心功能不全早期、甲状腺功能减退 | `ida_cn_2022`、`hypothyroid_cn_2017`、`hf_cn_2024` | — |
| K72 | 免疫力低下 · 反复感染 | 免疫功能低下、慢性鼻炎 / 鼻窦炎、贫血或营养不良 | **（无）** | — |
| K73 | 黄疸 · 眼睛发黄 · 皮肤发黄 | 肝细胞性黄疸、梗阻性黄疸（外科黄疸）、溶血性黄疸 | `dili_cn_2023`、`chb_cn_2022` | — |
| K74 | 肝区疼痛 · 右上腹痛 | 胆囊炎 / 胆结石、脂肪肝 / 肝炎、肝脓肿 | `nafld_cn_2018`、`chb_cn_2022`、`dili_cn_2023`、`biliary_inf_cn_2021` | — |
| K75 | 胰腺炎 · 上腹剧痛放射到后背 | 急性胰腺炎、消化性溃疡穿孔 | `ap_cn_2021` | — |
| K76 | 痔疮 · 肛门疼痛 · 肛周不适 | 内痔 / 外痔、肛裂、肛周脓肿 | `hemorrhoid_cn_2020` | — |
| K77 | 腹胀 · 腹水 · 肚子变大 | 功能性腹胀、肝硬化腹水、腹腔肿瘤 | `ascites_cn_2023` | — |
| K78 | 血尿 · 尿中带血 | 泌尿系感染、泌尿系结石、泌尿系肿瘤、肾小球肾炎 | **（无）** | — |
| K79 | 腰痛 · 肾绞痛 · 结石 | 输尿管结石、肾结石、腰肌劳损 | `cua_cn_2022` | — |
| K80 | 尿量异常 · 少尿无尿 | 急性肾损伤、尿路梗阻、慢性肾病 | `ckd_sh_2022` | — |
| K81 | 泡沫尿 · 蛋白尿 | 肾小球肾炎、糖尿病肾病、生理性泡沫尿 | `ckd_sh_2022`、`wst229_2024` | — |
| K82 | 眩晕 · 天旋地转 · 耳石症 | 良性阵发性位置性眩晕（耳石症）、梅尼埃病、前庭神经炎 | `bppv_cn_2017`、`vertigo_cn_2017` | — |
| K83 | 面瘫 · 口角歪斜 | 特发性面神经麻痹（贝尔面瘫）、中枢性面瘫（卒中）、带状疱疹引起的面瘫 | `facial_palsy_cn_2016` | — |
| K84 | 手麻 · 脚麻 · 周围神经病变 | 糖尿病周围神经病变、腕管综合征、颈椎病 / 腰椎病 | `dm_neuropathy_cn_2021` | — |
| K85 | 抽搐 · 癫痫发作 | 癫痫、热性惊厥、低血糖 / 电解质紊乱 | `epilepsy_cn_2015`、`fs_cn_2017` | — |
| K86 | 咯血 · 痰中带血 | 支气管炎 / 肺炎、肺结核、支气管扩张、肺恶性肿瘤 | `hemoptysis_bj_2020` | — |
| K87 | 下肢水肿 · 腿肿 | 心源性水肿、肾源性水肿、深静脉血栓、静脉曲张 / 久站 | `dvt_cn_2017`、`hf_cn_2024`、`ckd_sh_2022` | — |
| K88 | 甲状腺肿大 · 颈部包块 | 甲状腺结节、弥漫性甲状腺肿（甲亢 / 桥本）、甲状腺恶性肿瘤 | `thyroid_nodule_cn_2023`、`hyperthyroid_cn_2022` | — |
| K89 | 晕厥 · 眼前发黑 · 突然昏倒 | 体位性低血压、血管迷走性晕厥、心源性晕厥 | `syncope_cn_2018` | — |
| K90 | 乏力 · 容易累 · 没精神 | 贫血、甲状腺功能减退、糖尿病 / 血糖异常、睡眠障碍 / 抑郁情绪 | `ida_cn_2022`、`hypothyroid_cn_2017`、`dm_cn_2024` | — |
| K91 | 淋巴结肿大 | 反应性淋巴结增生、淋巴结结核、淋巴瘤 / 转移癌 | `lymphoma_nhc_2022` | — |
| K92 | 口腔溃疡 · 反复溃疡 | 复发性阿弗他溃疡、创伤性溃疡、白塞病 | `rau_cn_2012` | — |
| K93 | 耳闷 · 听力下降 · 突发性耳聋 | 突发性耳聋、耵聍栓塞、分泌性中耳炎 | `sshl_cn_2015` | — |
| K94 | 鼻出血 · 流鼻血 | 鼻腔黏膜干燥糜烂、鼻腔血管瘤 / 出血点、高血压相关鼻出血、血液系统疾病 | `epistaxis_cn_2015` | — |
| K95 | 抑郁情绪 · 兴趣减退 · 心理困扰 | 抑郁障碍、适应障碍、双相情感障碍抑郁相 | `mdd_cn_2025` | — |
| K96 | 儿童腹痛 · 哭闹不安 | 肠系膜淋巴结炎、肠套叠、急性阑尾炎 | **（无）** | `appendicitis_cn_2020` |
| K97 | 乳腺肿块 · 乳房疼痛 | 乳腺增生、乳腺纤维腺瘤、乳腺恶性肿瘤 | `mastopathy_cn_2016`、`bc_screen_cn_2021` | — |
| K98 | 前列腺症状 · 排尿困难（男性） | 良性前列腺增生、前列腺炎、前列腺恶性肿瘤 | `cua_cn_2022` | — |
| K99 | 骨质疏松 · 骨密度低 · 易骨折 | 原发性骨质疏松、继发性骨质疏松 | `osteoporosis_cn_2022` | — |
| K100 | 视力突然下降 · 眼前黑影遮挡 | 视网膜脱离、视网膜中央动脉阻塞、玻璃体出血、急性闭角型青光眼 | **（无）** | — |

## 没有找到可靠出处的条目

这些条目保持空白。原因多为：没有找到该症状/指标对应的中国指南或共识，或只在非一手来源（博客等）里看到，不满足登记标准。

- **K34** 电解质（高钾血症、低钾血症、低钠血症）
- **K67** 肌肉抽筋 · 腿抽筋（夜间腿部肌肉痉挛、低钙 / 电解质紊乱、下肢动脉供血不足）
- **K72** 免疫力低下 · 反复感染（免疫功能低下、慢性鼻炎 / 鼻窦炎、贫血或营养不良）
- **K78** 血尿 · 尿中带血（泌尿系感染、泌尿系结石、泌尿系肿瘤、肾小球肾炎）
- **K96** 儿童腹痛 · 哭闹不安（肠系膜淋巴结炎、肠套叠、急性阑尾炎）
- **K100** 视力突然下降 · 眼前黑影遮挡（视网膜脱离、视网膜中央动脉阻塞、玻璃体出血、急性闭角型青光眼）
