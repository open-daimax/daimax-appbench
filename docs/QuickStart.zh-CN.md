# 快速开始

本指南将引导您完成 `evalapp` 的安装、配置及首次评测。

## 环境要求

- **Python ≥ 3.10**
- **Git**（用于克隆仓库）
- Android 评测：已连接的设备或模拟器，需 ADB 访问权限
- iOS 评测：已连接的设备或模拟器
- Web 评测：无额外硬件要求

## 安装

```bash
git clone <your-repo-url> daimax-appbench
cd daimax-appbench

python -m venv .venv
source .venv/bin/activate
pip install -e .
```

验证安装：

```bash
evalapp --help
```

应看到 CLI 帮助信息，列出所有可用命令。

### 可选依赖

```bash
# 开发工具（pytest、覆盖率）
pip install -e ".[dev]"

# 性能加速（orjson 提供 3-5× JSON 编解码速度）
pip install -e ".[perf]"
```

## 配置

### 创建配置文件

```bash
cp evalapp.yaml.example evalapp.yaml
```

> **重要**：`evalapp.yaml` 包含敏感 API 密钥，已被 `.gitignore` 排除，请勿提交到版本控制。

### 配置项说明

| 分节 | 字段 | 说明 |
|------|------|------|
| `platforms` | — | 评测目标平台：`web`、`android`、`ios` |
| `results_dir` | — | 评测结果目录（默认 `results`） |
| `models.e2e` | `api_key` | E2E 视觉模型 API Key（环境变量 `MIDSCENE_MODEL_API_KEY`） |
| `models.e2e` | `base_url` | OpenAI 兼容协议地址（环境变量 `MIDSCENE_MODEL_BASE_URL`） |
| `models.e2e` | `name` | 模型名称，如 `gpt-4o`（环境变量 `MIDSCENE_MODEL_NAME`） |
| `models.aesthetics` | `api_key` | 美观度 VL 模型 API Key（环境变量 `DASHSCOPE_API_KEY`） |
| `models.aesthetics` | `base_url` | 模型端点（默认 DashScope） |
| `models.aesthetics` | `name` | 模型名称（默认 `qwen-vl-max`） |
| `ai_ui_test` | `timeout` | E2E 测试超时秒数（默认 300） |
| `ai_ui_test` | `replan_limit` | 单条用例最大重规划次数（默认 20） |
| `build_app` | `timeout` | 构建超时秒数（默认 1800） |
| `build_app` | `build_type` | 构建类型：`debug` 或 `release` |
| `install_app` | `timeout` | 安装超时秒数（默认 300） |
| `install_app` | `device_id` | 目标设备 ID（null 为自动检测） |

### 优先级顺序

配置按以下优先级解析（从高到低）：

1. `evalapp.yaml` 中的显式配置
2. 环境变量
3. 内置默认值（定义在 `evalapp/config.py`）

### 最小配置

至少需要配置 E2E 视觉模型才能运行评测：

```yaml
models:
  e2e:
    api_key: "your-api-key"
    base_url: "https://your-model-endpoint/v1"
    name: "gpt-4o"
```

美观度模型为可选项 —— 未配置时该维度将被跳过，权重自动重新归一化。

## 运行首次评测

### 评测 Web 应用

最简单的入门方式是评测已部署的 Web 应用：

```bash
evalapp evaluate --url https://my-app.vercel.app --sample-ids CoffeeRoastLog
```

执行流程：
1. 加载 `CoffeeRoastLog` 样本及其测试用例
2. 运行 TC_LAUNCH 启动门控检查
3. 逐条执行 E2E 测试用例
4. 对所有适用维度评分
5. 生成交互式 `report.html`（默认自动在浏览器中打开）

### 评测 APK

```bash
evalapp evaluate --apk ./build/app-debug.apk --sample-ids CoffeeRoastLog
```

### 从源码构建并评测

```bash
evalapp evaluate --project ./my-app --platform web --sample-ids CoffeeRoastLog
```

使用 `--project` 时必须显式指定 `--platform`，引擎会先构建项目再进行评测。

### 批量评测

评测数据集分类下的全部样本：

```bash
evalapp evaluate --workspace ./my_workspace \
    --samples-dir ./dataset/V2/beverage \
    --platform web
```

## 理解评测结果

### 报告

评测完成后，在工作区根目录（产物模式为 `--output` 目录）生成单文件交互式 HTML 报告，包含：

- **总分卡片**：总分及各维度分数明细
- **多端对比**：跨平台一致性对比视图（同时评测多个平台时）
- **逐样本明细**：启动截图、E2E 用例结果、后端验证、稳定性及美观度详情
- **多维筛选**：按平台、样本集、后端需求等条件过滤

### 评分维度

| 维度 | 权重构成 | 说明 |
|------|----------|------|
| 成功率 | 顶层指标 | 首次生成成功率 60% + 问题修复 20% + 需求补充 20% |
| 质量 | 顶层指标 | 功能完整性（含稳定性、后端完整性扣分） |
| 体验 | 顶层指标 | 耗时 60% + 包大小 20% + 美观度 20% |

缺失维度自动不计入评分，权重归一化重分配。

## 常见问题

### "No test cases found"

确认 `--sample-ids` 的值与 `dataset/V1/` 或 `dataset/V2/` 下的目录名完全匹配（区分大小写）。

### E2E 测试超时

在 `evalapp.yaml` 中增大超时设置：

```yaml
ai_ui_test:
  timeout: 600  # 秒
  replan_limit: 30
```

### 构建失败

- 确认项目依赖已正确安装
- 检查 `build_app.script_path` 是否指向有效的构建脚本
- 使用 `--stream-output` 查看实时构建日志

### 模型 API 报错

- 检查 API Key 是否正确配置（同时检查 `evalapp.yaml` 和环境变量）
- 确认 `base_url` 端点从当前机器可达
- 确认模型名称对所使用的服务商有效

## 下一步

- [API 参考](API.zh-CN.md) — 完整 CLI 命令与配置 Schema
- [架构设计](Architecture.md) — 系统设计与组件概述
