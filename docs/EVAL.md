# MedTriage 当前评测说明

版本日期：2026-10-29。当前工程验证以 ENGINEERING_VALIDATION.md 为准：真实后端 929 项通过，前端 171 项通过。原版外观还原使用隔离示例数据核对，不新增模型请求。

## 检索
本轮复跑 evals/run_retrieval_compare.py，默认 baseline：
- 50 条 golden：Top-1 0.900，Top-3 1.000，MRR@3 0.950。
- 95 条历史查询：Top-1 0.863，Top-3 0.989，MRR@3 0.918。
- 64 条作者自建留出查询：Top-1 0.766，Top-3 0.938，MRR@3 0.849。
- 10 条非医疗查询：误召回 0 条。
前两组参与过调优，只作为回归集；第三组也不是外部独立临床验证。
BM25 rerank/fuse 对留出 Top-1 改善 0.015，但历史回归 Top-3 降低 0.010，因此未默认启用。
完整结果、漏召回样本见 backend/evals/retrieval_compare.json。保留历史评测数据是为了复现，不包含旧版应用。

## 眼底
包内既有 test 评测 508 张：准确率 0.7657，QWK 0.8958，跨两级及以上错误 21 张，其中低估两级及以上 13 张。
1 级召回 0.534，3 级召回 0.577，需继续改进。valid 参与模型选择，不当作独立测试集。
本轮核对了混淆矩阵和权重指纹，没有重新训练或重新运行全部图像评测。
数据导出尺寸与训练图片不同，不能据此保证指标是性能下界。
细节与逐图记录见 backend/evals/fundus_report.json 和 fundus_rows_test.json。

## 安全
离线注入规则自建留出变体 8 条识别 7 条，良性 32 条未误报；这不是外部红队评测，不证明模型不会被攻破。
红旗规则、否定描述、账号切换迟到响应与报告同步由回归用例覆盖。
引用支持度为词面落点，不代表医学正确性；知识库 100 条中 94 条有来源，6 条待补。

## 真实模型与工具
文本正式版：文本、JSON、工具调用和流式输出实测通过。
原默认视觉分类失败已保留在 live_smoke_report.json 的 previous_vision_checks；视觉单独切换经济版后，合成化验单的类型与血糖 8.5、HbA1c 8.2 核对通过。
累计实际请求 8 次。报告 6/6 是核查项数量，不是请求数；合成识别不当作临床准确率。缓存探针本次未命中。
真实 MCP SDK 初始化、7 工具发现与 check_red_flags 调用通过。

## 已知限制
无真实用户试点、无多中心临床验证，未完成所有真实图片类型和公开部署场景的系统验证。
前端构建与图片、字体、图标和 3D 依赖均随新版包保留；旧 HTML 前端、设计归档及旧构建不分发。

## 14. 2026-11-10：回应预赛评审意见（眼底上传演示）· 技术说明书重写 · 红旗规则循证对照

预赛结果 88 分，评语：「MedTriage 眼底病变 AI 筛查专业，置信度清晰；建议增加眼底图片上传演示。」

| 改动 | 位置 | 说明 |
|---|---|---|
| 眼底上传演示 | `frontend/src/lib/fundusDemo.ts`、`EyePage.vue`、`WorkPage.vue`、`frontend/public/samples/` | 示例 A 与 `演示素材/01_眼底示例.jpg` 逐字节一致；示例 B 为同图高斯模糊 1.5（质量门控判为「不可评估」并建议重拍）。示例图按文件上传到 `/api/fundus/analyze`，与用户自选图片同一链路；五步进度在真实响应返回前停在「本地模型分级」 |
| 红旗规则循证对照 | `backend/safety.py` 的 `RULE_BASIS`、`tests/test_safety_basis.py` | 17/22 条规则 + 血糖数值规则对应已核实（high）的国内指南或共识，主题级对应；5 条暂无登记来源，如实留空 |
| 技术说明书 | `tools/build_technical_pdf.py` → `docs/技术说明书.pdf`（同步 `03_技术说明书.pdf`、`docs/技术说明书.md`） | 23 页；指标全部由评测数据现算：需转诊 DR（≥2 级）灵敏度 94.2%（211/224）、特异度 90.5%（257/284），ECE 0.041 |
| 化验单示例 | `frontend/src/lib/labDemo.ts`、`LabPage.vue`、`public/samples/lab-sample.png` | 合成化验单与 `演示素材/02_合成化验单.png` 逐字节一致，按文件上传到 `/api/ai/image` |
| 前端备用构建 | `tools/build_frontend_fallback.mjs`，`pack_submission.py` 在 Vite 失败时自动调用 | TypeScript + Vue 官方 SFC 编译器，零原生依赖；冒烟：浏览器产物全部模块执行 + 工作台 / 登录 / 落地页服务端渲染并核对关键文案 |
| 兼容性 | `backend/tests/test_pricing.py` | `datetime.UTC` 只在 Python 3.11+ 存在，改为 `timezone.utc`，与「Python 3.10+ 可运行」的说明一致 |

沙箱验证：后端 935 通过 / 0 失败（替身 Web 框架），前端 171 通过，`vue-tsc` 0 错误。真实 FastAPI、Vitest 与 Vite 生产构建以本机 `pack_submission.bat` 为准（脚本先构建、再测试，任何一步失败都不打包）。
