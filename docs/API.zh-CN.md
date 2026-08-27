# API 参考

`evalapp` CLI 命令、配置 Schema 及扩展点的完整参考文档。

## CLI 命令

### 命令总览

| 命令 | 说明 |
|------|------|
| `evalapp evaluate` | 评测产物或工作区代码（构建 → 安装 → E2E → 评分 → 报告） |
| `evalapp retest` | 重跑 E2E 测试并重新生成报告 |
| `evalapp report` | 为已完成的评测生成 / 重新生成报告 |
| `evalapp history` | 查看工作区的执行历史记录 |
| `evalapp migrate-workspace` | 迁移旧版工作区目录结构 |

### `evalapp evaluate`

主评测命令，支持三种模式：

#### 产物模式（推荐）

直接评测预构建产物：

```bash
# Web 应用（URL）
evalapp evaluate --url <url> --sample-ids <id> [OPTIONS]

# Android APK
evalapp evaluate --apk <path> --sample-ids <id> [OPTIONS]

# iOS 应用
evalapp evaluate --app <path> --sample-ids <id> [OPTIONS]

# 源码项目（需配合 --platform）
evalapp evaluate --project <dir> --platform <platform> --sample-ids <id> [OPTIONS]
```

#### 批量模式

从样本集目录批量评测：

```bash
evalapp evaluate --workspace <path> --samples-dir <dir> --platform <platform> [OPTIONS]
```

#### 执行计划模式

精细控制评测顺序与范围：

```bash
evalapp evaluate --workspace <path> --exec-plan <file> [OPTIONS]
```

#### 参数说明

| 参数 | 说明 |
|------|------|
| `--url` | 已部署的 Web 应用 URL（产物模式） |
| `--apk` | 预构建 Android APK 路径（产物模式） |
| `--app` | 预构建 iOS .app 路径（产物模式） |
| `--project` | 源码项目目录（产物模式，需配合 `--platform`） |
| `--output` | 结果输出目录（产物模式默认 `./eval_output`） |
| `--workspace` | 已有工程目录路径（产物模式可省略） |
| `--samples-dir` | 样本集目录（批量模式必填，与 `--exec-plan` 二选一） |
| `--exec-plan` | 执行计划 YAML 路径（与 `--samples-dir` 二选一） |
| `--platform` | 目标平台：`web` / `android` / `ios` |
| `--sample-ids` | 样本 ID 列表，逗号分隔（默认执行计划中的全部样本） |
| `--sample-id` | 单个样本 ID（已弃用，请使用 `--sample-ids`） |
| `--generator` | 生成器名称（默认从工作区目录名推断） |
| `--workers` | 并发评测线程数（默认 1） |
| `--show-browser` | 显示浏览器界面（有头模式），默认无头 |
| `--no-uninstall` | 评测完成后不卸载应用 |
| `--no-open-report` | 禁止自动打开浏览器查看报告 |
| `--wait-generate` | 流水线模式：按样本等待生成完成后立即投入评测 |

#### 平台自动推断

| 产物参数 | 推断平台 |
|----------|----------|
| `--url` | `web` |
| `--apk` | `android` |
| `--app` | `ios` |
| `--project` | 需显式指定 `--platform` |

### `evalapp retest`

为已评测的样本重跑 E2E 测试，无需重新构建或安装。

#### 单样本模式

```bash
evalapp retest --workspace <path> --sample-id <id> --platform <platform> [OPTIONS]
```

#### 多样本模式

```bash
evalapp retest --workspace <path> --sample-ids <id1>,<id2> --exec-plan <file> [OPTIONS]
```

#### 参数说明

| 参数 | 说明 |
|------|------|
| `--workspace` | 工作区路径（必填） |
| `--sample-id` | 单样本模式：指定样本 ID |
| `--sample-ids` | 多样本批量模式：逗号分隔的样本 ID 列表 |
| `--platform` | 目标平台（单样本模式必填） |
| `--exec-plan` | 执行计划 YAML（多样本模式推荐） |
| `--test-case-ids` | 指定重跑的用例 ID 列表（逗号分隔，仅单样本模式生效） |

### `evalapp report`

生成或重新生成评测报告。

```bash
# 为最新一次评测重新生成报告
evalapp report

# 指定 Run ID
evalapp report --run-id <run_id>

# 生成含历史对比的报告
evalapp report --compare

# 指定工作区重新生成汇总报告
evalapp report --workspace <workspace_path>
```

### 全局参数

所有命令通用：

| 参数 | 说明 |
|------|------|
| `--config` | 配置文件路径（默认 `evalapp.yaml`） |
| `--verbose` | 详细输出 |
| `--stream-output` | 实时输出子进程日志 |

## 配置 Schema

`evalapp.yaml` 定义所有运行时配置。完整带注释模板参见 `evalapp.yaml.example`。

### 顶层字段

```yaml
platforms: [web, android, ios]   # 评测目标平台
results_dir: results              # 结果输出目录
```

### 模型配置

```yaml
models:
  e2e:
    api_key: ""       # 视觉模型 API Key（环境变量 MIDSCENE_MODEL_API_KEY）
    base_url: ""      # OpenAI 兼容协议地址（环境变量 MIDSCENE_MODEL_BASE_URL）
    name: ""          # 模型名称（环境变量 MIDSCENE_MODEL_NAME）
    family: ""        # 模型系列标识（环境变量 MIDSCENE_MODEL_FAMILY）
  aesthetics:
    api_key: ""       # 美观度 VL 模型 Key（环境变量 DASHSCOPE_API_KEY）
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    name: "qwen-vl-max"   #（环境变量 AESTHETICS_MODEL）
    family: ""
```

### AI UI 测试配置

```yaml
ai_ui_test:
  timeout: 300          # 单条用例超时秒数
  replan_limit: 20      # 单条用例最大重规划次数
```

### 构建配置

```yaml
build_app:
  script_path: tools/build_app/scripts/build_app.py
  timeout: 1800         # 构建超时秒数
  build_type: debug     # debug | release
  clean: false          # 清洁构建
  android_output_format: apk   # apk | aab
  ios_output_format: app       # app | ipa
```

### 安装配置

```yaml
install_app:
  script_path: tools/install_app/scripts/install_app.py
  timeout: 300
  device_id: null       # null = 自动检测
  auto_install: false
```

### 可选集成

```yaml
# 外部模型服务（可选，增强评测能力）
external_service:
  enabled: false
  api_key: ""           # 环境变量 EXTERNAL_SERVICE_API_KEY

# MCP 工具服务（可选）
mcp:
  enabled: false
  servers: []
```

### 报告配置

```yaml
report:
  auto_open: true       # 自动打开报告
  eval_version: "2.0"   # 评测版本号
```

## 扩展点

框架使用 Python entry points 进行插件发现。姊妹仓可注册能力而无需修改本仓代码。

### 生成器插件

Entry point 组：`evalapp.generators`

注册 `AppGenerator` 子类以提供代码生成能力：

```toml
# 在你的包的 pyproject.toml 中
[project.entry-points."evalapp.generators"]
my_generator = "my_package.generator:MyGenerator"
```

运行时通过 `evalapp.generators.get_generator(name)` 发现。

### CLI 命令插件

Entry point 组：`evalapp.commands`

注册额外的 CLI 子命令，自动挂载到 `evalapp` 命令组：

```toml
# 在你的包的 pyproject.toml 中
[project.entry-points."evalapp.commands"]
generate = "my_package.commands:generate_cmd"
design-samples = "my_package.commands:design_samples_cmd"
```

启动时自动发现并挂载。

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 成功 |
| 1 | 一般错误（配置、文件缺失等） |
| 2 | CLI 用法错误（参数无效） |

## 样本 Schema

### `sample.yaml` 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `sample_id` | string | 唯一样本标识（与目录名一致） |
| `title` | string | 样本中文名 |
| `app_type` | string | 应用品类（传给美观度模型做品类感知评分） |
| `dataset_version` | string | 所属代际：`V1` 或 `V2` |
| `complexity` | string | 复杂度档位 |
| `requires_backend` | boolean | 是否需要真实后端 |
| `requires_auth` | boolean | 是否需要登录态 |
| `requirement` | string | 完整需求描述 |
| `pages` | list | 页面清单，含 `name`、`level`（L1/L2/L3）、`entry_from` |
| `navigation` | object | 导航结构（如 bottom tabs） |
| `core_functions` | list | 核心功能列表 |
| `constraints` | list | 工程约束 |
| `notes` | list | 验证重点 |

### 测试用例 Schema

```json
{
  "prompt_id": "SampleId",
  "platform": "default",
  "test_cases": [
    {
      "id": "TC002",
      "name": "用例名称",
      "description": "验证内容描述",
      "steps": [
        "操作 -> 预期: 结果"
      ],
      "expected_result": "整体预期结果",
      "priority": "P0",
      "category": "core_crud"
    }
  ]
}
```

#### 优先级

| 优先级 | 含义 |
|--------|------|
| `P0` | 最高 — 核心功能 |
| `P1` | 重要 — 次要功能 |
| `P2` | 可选 — 边缘场景 |

#### 分类

| 分类 | 说明 |
|------|------|
| `launch_check` | 应用启动验证 |
| `core_crud` | 核心 CRUD 操作 |
| `form_validation` | 表单输入与校验 |
| `navigation` | 页面导航与路由 |

历史优先级值（`high`、`medium`、`low`）加载时自动归一化。
