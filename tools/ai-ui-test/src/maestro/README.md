# Maestro 模块

将 Midscene UI 测试报告转换为 Maestro YAML 测试用例，支持运行 yaml.

## 架构设计

```
maestro/
├── types.ts           # 类型定义
├── converter.ts       # 核心转换器（接受 JSON，输出 YAML）
├── executor.ts        # 执行器（调用 maestro CLI）
├── index.ts           # 模块入口（包含辅助函数）
├── action_mapper.ts   # 动作映射逻辑
└── yaml_generator.ts  # YAML 生成器
```

## 核心功能

### 1. 转换器 (Converter)

**职责**：接受 Midscene 报告 JSON，转换为 Maestro YAML

```typescript
import { MaestroConverter } from './maestro/index.js';

const reportData = { /* Midscene JSON */ };
const converter = new MaestroConverter(reportData, {
  appId: 'com.example.app',
  name: '测试用例名称'
});

const result = converter.convert();
console.log(result.yaml);
```

**特性**：
- ✅ 自动从报告中提取屏幕尺寸
- ✅ 自动使用百分比坐标（如果有屏幕尺寸）
- ✅ 支持多种动作类型映射
- ✅ 智能忽略不需要的任务类型（Plan、Locate 等）

### 2. 辅助函数

**职责**：处理 HTML→JSON→YAML 的完整流程（在 index.ts 中）

```typescript
import { convertHtmlToYaml } from './maestro/index.js';

// 从 HTML 报告转换并保存
await convertHtmlToYaml(
  '/path/to/report.html',
  '/path/to/output.yaml',
  { appId: 'com.example.app' }
);
```

**如果已有 JSON 数据**，直接使用转换器：

```typescript
import { MaestroConverter } from './maestro/index.js';

const reportData = { /* JSON 数据 */ };
const converter = new MaestroConverter(reportData, {
  appId: 'com.example.app'
});

const result = converter.convert();
console.log(result.yaml);
```

### 3. 执行器 (Executor)

**职责**：调用 maestro CLI 执行测试

```typescript
import { executeMaestroTest, checkMaestroInstalled } from './maestro/index.js';

// 检查 Maestro 是否已安装
const installed = await checkMaestroInstalled();

// 执行测试
const result = await executeMaestroTest('/path/to/test.yaml', {
  deviceId: 'emulator-5554'
});

if (result.success) {
  console.log('测试通过！');
  console.log(result.output);
}
```

## 支持的动作映射

| Midscene 动作 | Maestro 命令 | 说明 |
|--------------|-------------|------|
| Tap/Click | tapOn | 点击（自动使用百分比坐标） |
| Input/Type | tapOn + inputText | 先点击输入框，再输入文本 |
| Scroll | scroll | 滚动屏幕 |
| Swipe | swipe | 滑动手势 |
| Sleep | delay | 延迟等待（毫秒） |
| Assert | assertVisible | 断言元素可见 |
| Wait | extendedWaitUntil | 等待元素出现 |

**忽略的任务类型**：Plan、Locate、Planning

**未知动作**：输出 warning，不会中断转换

## 使用示例

### 完整流程示例

```typescript
import { 
  convertHtmlToYaml, 
  executeMaestroTest,
  checkMaestroInstalled 
} from './maestro/index.js';

// 1. 转换报告为 YAML
const result = await convertHtmlToYaml(
  './report.html',
  './test.yaml',
  { 
    appId: 'com.example.mapapp',
    name: '搜索功能测试'
  }
);

if (!result.success) {
  console.error('转换失败:', result.error);
  process.exit(1);
}

console.log(`✅ 转换成功，生成了 ${result.commandCount} 个命令`);

// 2. 检查 Maestro 是否已安装
if (!await checkMaestroInstalled()) {
  console.error('❌ Maestro 未安装');
  process.exit(1);
}

// 3. 执行测试
const execResult = await executeMaestroTest('./test.yaml');

if (execResult.success) {
  console.log('✅ 测试通过！');
  console.log(execResult.output);
} else {
  console.error('❌ 测试失败:', execResult.error);
}
```

### 只转换不执行

```typescript
import { MaestroConverter } from './maestro/index.js';
import { extractReportJsonFromHtml } from '../helper/midscene_report_helper.js';

// 1. 提取 JSON
const reportData = await extractReportJsonFromHtml('./report.html');

// 2. 转换
const converter = new MaestroConverter(reportData, {
  appId: 'com.example.app'
});

const result = converter.convert();

// 3. 使用 YAML
console.log(result.yaml);
```

## 转换选项

```typescript
interface ConversionOptions {
  /** 应用包名/Bundle ID（必需） */
  appId: string;
  
  /** 测试用例名称（可选，不提供则从报告中提取） */
  name?: string;
  
  /** 标签（可选） */
  tags?: string[];
  
  /** 是否优先使用文本选择器（可选，默认 false） */
  preferTextSelectors?: boolean;
}
```

## 自动特性

以下特性会自动从报告中解析，无需手动配置：

1. **屏幕尺寸**：从 `uiContext.shotSize` 自动提取
2. **百分比坐标**：如果有屏幕尺寸，自动使用百分比坐标
3. **测试名称**：如果未提供，从报告的第一个 execution 中提取

## 输出示例

### 输入：Midscene 报告

```json
{
  "executions": [{
    "name": "搜索天坛",
    "uiContext": {
      "shotSize": { "width": 1084, "height": 2412 }
    },
    "tasks": [
      {
        "type": "Action Space",
        "subType": "Tap",
        "param": { "locate": { "center": [373, 1423] } },
        "thought": "点击搜索栏"
      },
      {
        "type": "Action Space",
        "subType": "Input",
        "param": { "value": "天坛" },
        "thought": "输入天坛"
      },
      {
        "type": "Action Space",
        "subType": "Sleep",
        "param": { "value": "1000" }
      }
    ]
  }]
}
```

### 输出：Maestro YAML

```yaml
appId: com.example.mapapp
---
# 点击搜索栏
- tapOn:
    point: "34.4%,59.0%"
# 输入天坛
- tapOn:
    point: "34.4%,59.0%"
- inputText: 天坛
- delay: 1000
name: 搜索天坛
```

## 注意事项

1. **百分比坐标**：自动启用，提高跨设备兼容性
2. **忽略列表**：Plan、Locate、Planning 类型的任务会被自动忽略
3. **未知动作**：会输出 warning 但不会中断转换
4. **失败任务**：有 error 或 status='failed' 的任务会被跳过

## 依赖

- **上层依赖**：`../helper/midscene_report_helper.ts` - 提供 HTML 报告解析功能
- **外部依赖**：`maestro` CLI - 执行测试时需要

## 测试

```bash
# 创建测试脚本
cat > test_maestro.ts << 'EOF'
import { convertHtmlToYaml } from './src/maestro/index.js';

const result = await convertHtmlToYaml(
  './report.html',
  './output.yaml',
  { appId: 'com.example.app' }
);

console.log(result.success ? '✅ 成功' : '❌ 失败');
EOF

# 运行测试
npx tsx test_maestro.ts
```

## 更新日志

### v2.0.0 (2026-03-12) - 架构重构

- ✅ 简化架构，移除过度设计
- ✅ 使用忽略列表替代复杂的 shouldSkipTask 逻辑
- ✅ 将 HTML 提取逻辑移到上层 helper 目录
- ✅ 移除 CLI 工具，改为代码调用
- ✅ 新增 executor 模块支持执行测试
- ✅ 自动从报告提取屏幕尺寸和使用百分比坐标

### v1.1.0 (2026-03-12)

- ✅ 新增 Sleep 动作支持
- ✅ 新增百分比坐标支持
- ✅ 新增文本选择器优先模式

### v1.0.0 (初始版本)

- ✅ 基本的动作映射功能
- ✅ HTML 和 JSON 报告支持