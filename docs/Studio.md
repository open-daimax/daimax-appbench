# AppBench Studio

统一的本地开源控制台：快速评测和完整评测共用导航、工作台与记录入口。布局参考 DaiMax 控制台；不依赖 FastApp 账号、内部生成器、数据库、诊断服务或私有接口。快速评测页面和核心保持独立，方便继续同步上游。

## 启动

在仓库根目录执行（Python 3.10+）：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[quickcheck]'
python -m playwright install chromium
cp evalapp.yaml.example evalapp.yaml  # 首次安装；不要覆盖已有配置
# 编辑 evalapp.yaml，填写自己的模型配置
evalapp --config evalapp.yaml studio --port 8766
# 或 ./scripts/start-studio.sh
```

打开 http://127.0.0.1:8766 。仓库包含构建好的页面，运行不需要 Node.js。控制台仅监听本机；目前不提供多用户认证和公网部署。8766 与快评启动脚本的默认端口相同，两者同时运行时请换一个端口。

## 两种评测

- **快速评测**：保留现有 URL 检测、模型配置、截图、评分规则与历史结果；仍使用配置中的 `workspace_root/quickcheck`，旧的 `quickcheck-ui` 命令保持兼容。
- **完整评测**：选择 Web URL、源码目录、Android APK、iOS `.app` 或已有工作区；选择相匹配的标准样本和并发数，再提交任务。支持查看实时日志、重用任务参数和打开已有 HTML 报告。报告和截图/E2E 报告会归档，后续重测不会覆盖历史记录。
- **评测记录**：同页列出完整任务和快评案例。两者的评分口径不同，不混排分数。

完整评测直接调用 `evalapp evaluate`。URL/源码/安装包模式从仓库 `dataset` 查找样本（表单展示 V2 样本）；已有工作区模式可指定样本目录，样本 ID 应与所选目录一致。路径是运行控制台机器上的路径，不是浏览器上传。已有工作区应符合 CLI 的样本工程结构，执行评测会更新其中的评测结果。

完整评测使用 `models.e2e`、`models.aesthetics`；快评使用其自身模型设置。修改配置文件后新建的完整评测子进程会重新读取配置。完整评测的 SDK、设备、测试工具准备参见 [快速开始](QuickStart.zh-CN.md)。仅安装控制台不代表设备和 E2E 环境已经就绪。

每次只运行一个完整评测任务，任务内可配置 1–8 个样本并发，快评保留自己的并发控制。CLI 成功退出且产生新的报告才会标记完成；报告中的测试失败不等于调度失败。任务失败请展开日志。Ctrl+C 停止接收请求，并等待已开始的任务结束；异常退出后残留任务在下次启动标记为中断。

## 数据与开发

完整任务默认保存到 `workspace_root/studio/full/<task-id>/`，包含 `job.json`、`output.log`、产物工作区及归档报告。`studio --output /path/to/studio` 仅覆盖控制台任务目录，不迁移快评数据。已有 CLI 完整评测结果不会自动导入任务列表。结果、日志和报告可能包含应用内容，分享前请检查。

```bash
cd report-ui
npm ci
npm run build:studio  # 更新 evalapp/studio/static/studio.html
npm run dev:studio   # 打开 /studio.html；API 代理到本机 8766
```

前端：`report-ui/src/studio/`；本地 API：`evalapp/studio/`；CLI：`evalapp/commands/studio.py`。快评通过同源 `/quickcheck.html` 复用页面，原 API 不变。新接口为 `/api/studio/{meta,samples,jobs}` 和 `/api/studio/jobs/<id>`；POST jobs 创建任务。报告服务仅公开任务归档产物，不公开源码和配置目录。

```bash
python -m pytest tests/test_studio.py -q
STUDIO_RUN_BROWSER_TESTS=1 python -m pytest tests/test_studio_browser.py -q
```
