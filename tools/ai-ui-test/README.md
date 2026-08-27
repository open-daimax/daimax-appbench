# AI UI Test - 移动端 UI 自动化测试工具

基于 Midscene.js 的 AI 驱动移动端 UI 自动化测试工具，支持自然语言描述测试步骤和断言，自动执行 UI 操作并生成测试报告。

## 功能特性

- 🤖 **AI 驱动**：自然语言描述测试步骤和断言，无需编写复杂脚本
- 📱 **多平台支持**：Android、Harmony、iOS 三大移动平台
- 🎯 **步骤与断言分离**：操作步骤和验证点独立，测试意图更清晰
- 📊 **智能报告**：自动生成详细 HTML 测试报告，包含截图和操作记录
- 🔄 **双执行策略**：AI 探索执行 + YAML 固化回放，首次智能化、后续稳定化
- 🚀 **快速启动**：支持 scheme/deeplink 直达目标页面

## 前置要求

- **Node.js**：>= 18.0.0
- **Android**：Android SDK Platform Tools（`adb`）
- **Harmony**：Harmony DevEco Studio（`hdc`）
- **iOS**：Xcode 命令行工具、iOS 模拟器（仅支持模拟器，真机不再支持）

## 安装和使用

### 安装

```bash
# 在本目录安装依赖（postinstall 会自动安装 Playwright chromium）
npm install
# 首次构建
npm run build
```

### 使用

```bash
# 全局命令
ai-ui-test "<操作步骤>" "<断言验证>"

# 本地开发
npx tsx src/index.ts "<操作步骤>" "<断言验证>"
```

### 完整示例

```bash
npx tsx src/index.ts "搜索天坛，骑行导航到天坛公园" "导航已开始，预计耗时不超过3小时" \
  --platform harmony \
  --app "示例地图应用" \
  --package com.example.mapapp \
  --knowledge "POI 弹窗中的'路线'是多种导航方式可以切换"
```

### 命令行参数

- `<steps>` - UI 操作步骤描述（自然语言）
- `<assertion>` - 断言验证描述（自然语言）
- `-p, --platform <type>` - 平台类型 (android|ios|harmony)
- `-a, --app <name>` - 应用名称
- `-P, --package <id>` - 包名/Bundle ID（**必需**，用于 YAML 转换）
- `-d, --device-id <id>` - 指定设备 ID
- `-s, --scheme <url>` - 启动 scheme/deeplink
- `-k, --knowledge <text>` - 业务知识

## 双执行策略

工具支持两种测试执行方式，根据场景自动选择或切换：

### 1. AI 探索执行（Midscene）

**适用场景**：首次执行、界面变化、探索性测试

**特点**：
- 基于 AI 视觉理解，自动识别界面元素
- 支持自然语言描述，灵活适应界面变化
- 执行过程中自动生成详细报告

**触发条件**：
- 未找到对应 YAML 文件
- YAML 执行失败时自动降级

### 2. YAML 固化回放（Maestro）

**适用场景**：回归测试、稳定流程、快速执行

**特点**：
- 基于坐标和元素定位，执行速度快
- 不依赖 AI 模型，成本更低
- 适合频繁执行的固定流程

**触发条件**：
- 已存在对应 YAML 文件
- 平台支持（Android、iOS）

### 执行策略流程

```
开始测试
    │
    ▼
检查是否存在 YAML 文件 ──否──► AI 探索执行（Midscene）
    │                              │
    是                              ▼
    │                        测试成功？
    ▼                              │
YAML 执行（Maestro）              是
    │                              │
    ▼                              ▼
执行成功？                  转换为 YAML 文件
    │                              │
    ├── 是 ◄───────────────────────┘
    │
    否
    │
    ▼
降级到 AI 探索执行
```

### 平台支持矩阵

| 平台 | AI 探索 | YAML 回放 | 说明 |
|------|---------|-----------|------|
| Android | ✅ | ✅ | 双模式都支持 |
| iOS | ✅ | ✅ | 双模式都支持 |
| Harmony | ✅ | ❌ | 仅支持 AI 探索 |

### YAML 文件管理

- **存储位置**：`.test_intermediates/maestro_{caseId}-{deviceId}.yaml`
- **生成时机**：AI 探索执行成功后自动转换
- **命名规则**：基于用例 ID 和设备 ID，确保设备隔离

### 使用建议

| 场景 | 推荐方式 | 原因 |
|------|----------|------|
| 新功能测试 | AI 探索 | 界面不稳定，需要灵活适配 |
| 回归测试 | YAML 回放 | 流程稳定，追求执行效率 |
| 跨设备执行 | 重新 AI 探索 | YAML 与设备绑定，不同设备需重新生成 |
| CI/CD 集成 | YAML 回放 | 速度快、成本低、结果稳定 |

## iOS 设备配置

### WebDriverAgent (WDA) 管理

工具自动管理 WebDriverAgent，无需网络下载：

1. **内置资源**：模拟器 WDA 内置于 `vendor/WDA_simulator.zip`
2. **首次解压**：首次使用时自动解压到 `cache/ios/` 目录
3. **自动安装**：检测到模拟器后通过 `simctl` 自动安装

### 仅支持模拟器

iOS 测试仅支持模拟器，真机不再支持。选择真机会报错：「真机 WDA 已不再支持，请使用 iOS 模拟器运行测试」。

## 输出格式

**成功时：**
```json
{
  "success": true,
  "reason": "断言验证的详细分析说明",
  "reportPath": "/path/to/report.html",
  "duration": 60000,
  "stepsDuration": 45000,
  "assertionDuration": 5000
}
```

**失败时：**
```json
{
  "success": false,
  "error": "错误信息",
  "errorType": "STEPS_EXECUTION_ERROR"
}
```

### 错误类型

| 错误类型 | 含义 | 应对方法 |
|---------|------|---------|
| `ENVIRONMENT_ERROR` | 设备未找到、工具不可用 | 检查设备连接和工具安装 |
| `STEPS_EXECUTION_ERROR` | UI 操作失败 | 简化步骤、补充业务知识 |
| `ASSERTION_FAILED` | 断言验证失败 | 通常表示发现 bug |
| `UNKNOWN_ERROR` | 其他错误 | 查看详情、重试 |

## 常见问题

**Q: 提示 "adb not found" 或 "hdc not found"？**

确保已安装对应平台开发工具：
```bash
adb version  # Android
hdc version  # Harmony
```

**Q: 如何查看详细调试信息？**

```bash
DEBUG=true ai-ui-test "测试需求"
```

**Q: 测试报告保存在哪里？**

默认保存在 `./midscene_run/report/` 目录。

**Q: 为什么 Harmony 不支持 YAML 回放？**

Maestro 框架本身不支持 HarmonyOS 平台，仅支持 Android 和 iOS。

## 技术栈

- **TypeScript**：类型安全的 JavaScript 超集
- **Midscene.js**：AI 驱动的 UI 自动化测试框架
- **Maestro**：移动端 UI 测试框架（Android/iOS）
- **Node.js**：JavaScript 运行时环境

## 更新日志

### v2.1.0 (2026-03-18)

- 🔄 **双执行策略**：支持 AI 探索执行和 YAML 固化回放两种模式
- 📱 **平台适配**：Android/iOS 支持双模式，Harmony 仅支持 AI 探索
- 📝 **智能转换**：AI 执行成功后自动生成 YAML 文件供后续回放

### v2.0.0 (2026-03-04)

- 🎯 **步骤与断言分离**：操作步骤和验证点独立为两个参数
- 📱 **多平台支持**：新增 Harmony 和 iOS 平台
- 🚀 **快速启动**：支持 scheme/deeplink

### v1.0.0 (2026-03-02)

- ✨ 初始版本发布
- 🤖 支持 AI 驱动的 Android UI 自动化测试
