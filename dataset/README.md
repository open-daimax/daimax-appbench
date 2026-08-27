# 样本集目录

## 概述

`dataset/` 目录存放评测样本集，按版本（V1 / V2）组织。每个版本下按类别分目录，每个样本一个子目录，含 `sample.yaml`（需求描述）与 `test_cases_default.json`（测试用例）。

## 目录结构

```
dataset/
├── V1/                 # V1 样本集
│   ├── index.yaml      # 样本集总索引
│   ├── games/          # 分类目录（各自含 index.yaml）
│   ├── tools/
│   ├── social/
│   ├── lifestyle/
│   ├── health/
│   ├── education/
│   └── ecommerce/
├── V2/                 # V2 样本集（无顶层 index.yaml，按类别索引）
│   ├── games/
│   ├── tools/
│   ├── social/
│   └── ...
└── ...（aesthetics_rules.yaml 已移至 evalapp/evaluation/metrics/collectors/）
```

## 执行计划

执行计划（Execution Plan）定义「哪些样本 × 哪些平台」参与评测，实现样本集定义与执行策略的解耦。

### 动态生成

Web 评测平台通过 `evalapp/web/services/exec_plan_builder.py` 的 `build_exec_plan()` **动态生成**执行计划 YAML 文件，写入工作区目录供 CLI 消费。用户在 Web 界面选择样本和平台后，系统自动生成对应的执行计划，无需手动编写。

### 执行计划文件格式

```yaml
version: "1.0"
name: "执行计划名称"
description: "执行计划描述"

# 引用样本集（相对于项目根目录）
datasets:
  - dataset/V1/games
  - dataset/V1/tools

# 执行任务列表
tasks:
  - order: 1
    sample_id: HappyMatch
    platform: android
    notes: "开心消消乐 - Android版本"

  - order: 2
    sample_id: CoffeeDiary
    platform: ios
    notes: "咖啡日记 - iOS版本"
```

### 关键字段说明

- **datasets**: 声明该执行计划需要的样本集路径（相对于项目根目录）
- **tasks**: 具体的执行任务列表
  - `order`: 执行顺序
  - `sample_id`: 样本 ID（必须在声明的样本集中存在）
  - `platform`: 目标平台（web / android / ios）
  - `end_case`: 结束测试用例 ID（可选，如 "TC003"，执行到该用例就停止）
  - `parallel_group`: 并行组（多平台场景使用，同组共享生成产物）
  - `skip_generate`: 是否跳过代码生成（多平台场景，同一样本只需生成一次）
  - `notes`: 备注信息（可选）

### CLI 使用方式

快捷模式通过 `--samples-dir` + `--platform` 直接指定评测范围：

```bash
# 评测指定类别目录的全部样本
evalapp evaluate --workspace my_workspace \
    --samples-dir ./dataset/V2/games \
    --platform android

# 评测单个样本
evalapp evaluate --workspace my_workspace \
    --samples-dir ./dataset/V2/games \
    --platform ios \
    --sample-ids HappyMatch

# 评测整个 V2 数据集
evalapp evaluate --workspace my_workspace \
    --samples-dir ./dataset/V2 \
    --platform web
```

高级用法可通过 `--exec-plan` 指定自定义执行计划：

```bash
evalapp evaluate --workspace my_workspace --exec-plan /path/to/exec_plan.yaml
```

> **注**: Web 平台动态生成的执行计划文件位于工作区目录下（如 `exec_plan_{task_id}.yaml`），CLI 直接引用该路径即可。

### end_case 字段说明

`end_case` 是任务级别的可选字段，用于快速验证时限制执行的测试用例数量。

- 测试用例按 ID 排序（TC001, TC002, TC003, ...）
- 设置 `end_case: "TC003"` 会执行从 TC001 到 TC003 的所有测试用例
- 如果 `end_case` 指定的用例不存在，会执行所有测试用例并记录警告

```yaml
tasks:
  # 只执行 TC001、TC002、TC003 三个测试用例
  - order: 1
    sample_id: HappyMatch
    platform: android
    end_case: "TC003"
    notes: "开心消消乐 - Android（快速验证）"

  # 执行所有测试用例
  - order: 2
    sample_id: HappyMatch
    platform: ios
    notes: "开心消消乐 - iOS（完整测试）"
```

### 验证执行计划

执行计划加载时会自动验证：
- 所有引用的样本集路径是否存在
- 所有任务中的 sample_id 是否在样本集中存在

如果验证失败，会抛出明确的错误信息。

## 注意事项

1. `datasets` 中的路径是相对于项目根目录的
2. `sample_id` 必须在声明的样本集中存在
3. 执行计划文件必须是有效的 YAML 格式
