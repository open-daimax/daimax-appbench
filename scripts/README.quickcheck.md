# QuickCheck 页面启动

```bash
uv sync --extra quickcheck
.venv/bin/python -m playwright install chromium
cp evalapp.yaml.example evalapp.yaml
./scripts/start-quickcheck.sh
```

默认地址 http://127.0.0.1:8766/，前后端同源；已包含构建好的 HTML，运行不需要 Node.js。本机页面可配置模型和凭据，也可先编辑 evalapp.yaml 并设置 QUICKCHECK_API_KEY。该文件已忽略；不要提交真实密钥。

改端口：`QUICKCHECK_PORT=8770 ./scripts/start-quickcheck.sh`。

仅修改前端源码时重新构建：`QUICKCHECK_BUILD_UI=1 ./scripts/start-quickcheck.sh`，此时才需要 Node.js 和 npm，脚本从公开 npm 源安装依赖。

Linux 首次运行安装系统库：`.venv/bin/python -m playwright install --with-deps chromium`。Ctrl+C 停止。

输出默认是 workspace_root/quickcheck，可用 QUICKCHECK_OUTPUT 覆盖；读取既有 cases/snapshots/policies/runs 结构时可指定旧目录。早期平铺 qc_* 结构不再支持。

局域网共享使用 `QUICKCHECK_SHARE_HOST=<本机网卡IP>`、可选 QUICKCHECK_SHARE_PORT；共享入口可查看与提交，不提供模型配置管理，不设登录，只在可信网络使用。

能力、评分指标与示例见 [QuickCheck](../docs/QuickCheck.md)，后续更新方式见 [同步维护](../docs/QuickCheck-Maintenance.md)。
