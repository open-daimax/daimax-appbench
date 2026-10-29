# QuickCheck 同步维护

完整评测继续由本仓维护。快评核心以独立模块为维护来源，本仓内嵌快评作为可审计的同步副本，因此公开用户无需访问内部仓库、相邻目录或额外安装未发布的包。

## 哪些文件由谁维护

| 内容 | 本仓位置 | 更新方式 |
|---|---|---|
| 快评核心、配置、存储、独立 CLI 适配器 | evalapp/quickcheck/ | 从独立模块 src/appbench_quickcheck 同步，包名转换为 evalapp.quickcheck |
| 快评静态 HTML | evalapp/quickcheck/static/ | 同步独立模块构建产物；源码变化后先在独立模块构建 |
| 快评页面源码 | report-ui/src/quickcheck/ | 从独立模块 ui/src 同步 |
| 核心回归测试 | tests/test_quickcheck_*.py | 同步独立模块 tests，替换 import 命名空间 |
| EvalApp 配置、命令注册与工作区接入 | evalapp/commands/quickcheck.py、evalapp/config.py、evalapp/cli.py | 本仓手工维护，不由同步覆盖 |
| 公开文档、真实示例截图与报告前端集成 | README*、docs/、report-ui/package.json、Vite 配置 | 本仓维护，按当前公开使用方式说明 |

只复制公开核心、UI 与测试；不导出服务端目录、真实 YAML、凭据、运行数据、依赖目录或内部仓库地址。许可证和素材来源仍需单独维护。

## 更新流程

1. 在独立模块修改并测试；如 UI 改动，重新生成其 static/quickcheck.html；先创建独立模块提交。
2. 在本仓执行同步，source 使用本地已提交且工作区干净的独立模块路径：

```bash
python scripts/sync-quickcheck.py --source /path/to/standalone-quickcheck
python scripts/sync-quickcheck.py --source /path/to/standalone-quickcheck --check
```

3. 检查 git diff、更新 README/示例并运行本仓完整回归：

```bash
pip install -e '.[dev,quickcheck]'
pytest -q
python -m playwright install chromium
QUICKCHECK_RUN_BROWSER_TESTS=1 pytest -q tests/test_quickcheck_browser_smoke.py
```

4. 审核后提交本仓。同步脚本不会访问网络，不提交或推送 Git，不改本地模型配置。第一次同步前应备份原快评未提交改动。

`docs/quickcheck-sync.json` 记录来源提交、源文件与导出文件 SHA256。`tests/test_quickcheck_sync.py` 检查生成文件是否漂移，防止两边静默分叉。EvalApp 适配器、文档和展示图不会被同步脚本覆盖。

## 发布边界

独立来源的提交 SHA 只用于追溯；公开运行不访问该提交或其私有远程。公开发布前审查图像素材来源，确保 LICENSE/NOTICE 与实际随包素材对应。Python wheel 随 evalapp 包含快评 HTML，基本 CLI 不需要 Playwright 浏览器；执行真实采集时才需要安装可选 quickcheck 依赖与浏览器。

如果以后独立快评包发布到公共包索引，再评估切换为版本依赖；当前不在公开安装命令中引用内部 GitLab 或尚未发布的包。
