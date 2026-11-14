# MedTriage 工程验证与复现

核验日期：2026-11-14。源码版本：2026-11-13 提交版。

## 本机真实环境结果

| 项目 | 结果 |
|---|---|
| 后端 FastAPI / pytest | 964 passed，0 failed，0 skipped；25.46 秒 |
| 前端 Vitest | 194 passed，15 个测试文件 |
| Vue / TypeScript | 类型检查通过 |
| Vite | 生产构建通过，构建产物随仓库提供 |
| LFS 权重下载 | 独立克隆后大小与 SHA-256 一致 |
| 源码核对 | 168 个应用、测试和工具代码文件与团队提交版本一致 |
| 公网访问 | 首页与 /api/health 返回 HTTP 200，健康状态 ok |

后端、前端测试覆盖账号隔离、鉴权、请求契约、报告渲染、SSE、规则闸门、引用、图像质量、样例流程和模块依赖等场景。

## 复现环境与命令

准备 Python 3.10+；前端开发与重建使用 Node.js 20+。

```bash
python -m pip install -r backend/requirements.txt numpy
cd backend
python -m pytest -q
```

```bash
cd frontend
npm ci
npx vitest run
npm run build
```

NumPy 用于图像质量检测，首次环境安装时应显式包含。真实眼底推理另需 PyTorch、torchvision 与完整权重。

## 自动化工作流

工作流位于 `.github/workflows/ci.yml`，包含后端风格检查、编译、测试、知识来源校验与检索门禁，以及前端类型、测试与构建。
本机验证与 GitHub 工作流分别记录：前端云端验证已通过，后端云端工作流尚未全部通过，详情以 [Actions](https://github.com/llu799529-lang/chuanzhi-web/actions) 的对应提交日志为准。

## 在线与模型验证范围

2026-11-14 的公网检查为只读访问，线上前端 app-dd143a51.js 与团队运行包相符。未通过服务器文件系统核对全部后端文件。
仓库前端使用相同源码的 Vite 构建；公网运行包使用相同源码的备用构建。

真实模型协议验证记录在 `backend/evals/live_smoke_report.json`，时间为 2026-10-29，累计 8 次请求、6 项核查。当前文本与视觉分别配置，合成化验单用于核对类型、血糖和 HbA1c 字段。
原始探针结果保留在报告中；合成样例验证与临床准确率分别表述。此次文档整理没有新增模型请求。

## 数据与使用范围

眼底模型、检索和规则评测见 [EVAL.md](EVAL.md)；公开数据上的回顾性评测与实际医疗效果验证分别记录。
测试结果适用于所列环境与已覆盖用例。系统提供筛查与就医信息参考，不能替代医生诊断。
