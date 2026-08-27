/**
 * Midscene 到 Maestro 的核心转换器
 * 职责：接受 JSON 数据，转换为 Maestro YAML
 */

import { mapActionToCommands, optimizeCommands } from './action_mapper.js';
import type { ConversionOptions, ConversionResult, MaestroCommand, MidsceneReport, MidsceneReportTask, PlatformConfig } from './types.js';
import type { Platform } from '../types.js';
import { logger } from '../helper/logger.js';

// 需要忽略的任务类型
const IGNORED_TASK_TYPES = ['Plan', 'Locate', 'Planning'];

/**
 * Maestro 转换器类
 */
export class MaestroConverter {
  private reportData: MidsceneReport;
  private options: ConversionOptions;
  private screenSize?: { width: number; height: number };
  private targetPlatform?: Platform;
  private deviceId?: string;

  constructor(reportData: MidsceneReport, options: ConversionOptions, targetPlatform?: Platform, deviceId?: string) {
    this.reportData = reportData;
    this.options = options;
    this.targetPlatform = targetPlatform;
    this.deviceId = deviceId;
    this.screenSize = this.extractScreenSize();
  }

  /**
   * 从报告中提取屏幕尺寸
   */
  private extractScreenSize(): { width: number; height: number } | undefined {
    const executions = this.reportData.executions || [];
    
    for (const execution of executions) {
      if (execution.uiContext?.shotSize) {
        const { width, height } = execution.uiContext.shotSize;
        if (width && height) return { width, height };
      }

      if (execution.tasks) {
        for (const task of execution.tasks) {
          if (task.uiContext?.shotSize) {
            const { width, height } = task.uiContext.shotSize;
            if (width && height) return { width, height };
          }
        }
      }
    }

    return undefined;
  }

  /**
   * 执行转换
   */
  convert(): ConversionResult {
    try {
      const executions = this.reportData.executions || [];
      if (executions.length === 0) {
        return { success: false, error: '报告中没有找到任何执行记录' };
      }

      // 收集所有任务
      const allTasks: MidsceneReportTask[] = [];
      for (const execution of executions) {
        if (execution.tasks && Array.isArray(execution.tasks)) {
          allTasks.push(...execution.tasks);
        }
      }

      if (allTasks.length === 0) {
        return { success: false, error: '报告中没有找到任何任务' };
      }

      // 映射为 Maestro 命令
      const commands: MaestroCommand[] = [];
      const comments = new Map<number, string>();
      let lineNumber = 2;

      for (const task of allTasks) {
        // 跳过非 Action Space 类型
        if (task.type !== 'Action Space') {
          continue;
        }

        // 跳过忽略列表中的任务
        if (task.subType && IGNORED_TASK_TYPES.includes(task.subType)) {
          continue;
        }

        // 跳过失败的任务
        if (task.error || task.status === 'failed') {
          continue;
        }

        // 转换任务为动作
        const action = this.taskToAction(task);
        if (!action) continue;

        // 映射动作为命令
        const actionCommands = mapActionToCommands(action, {
          ...this.options,
          usePercentageCoordinates: !!this.screenSize,
          screenSize: this.screenSize,
          targetPlatform: this.targetPlatform,
        });

        if (actionCommands.length === 0) {
          logger.warn(`未知的动作类型: ${task.subType}`);
          continue;
        }

        // 添加注释
        if (task.thought && actionCommands.length > 0) {
          comments.set(lineNumber, task.thought);
        }

        commands.push(...actionCommands);
        lineNumber += actionCommands.length;
      }

      // 优化命令序列
      const optimizedCommands = optimizeCommands(commands);

      if (optimizedCommands.length === 0) {
        return { success: false, error: '没有生成任何有效的 Maestro 命令' };
      }

      // 生成 YAML
      let yaml = generateYaml(
        optimizedCommands,
        this.options.appId,
        this.options.name || this.extractTestName(),
        this.options.tags,
        this.options.platform
      );

      // 添加注释
      yaml = addComments(yaml, comments);

      return {
        success: true,
        yaml,
        commandCount: optimizedCommands.length,
        deviceId: this.deviceId
      };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : String(error)
      };
    }
  }

  /**
   * 从报告中提取测试名称
   */
  private extractTestName(): string | undefined {
    const executions = this.reportData.executions || [];
    return executions[0]?.name;
  }

  /**
   * 将任务转换为动作格式
   */
  private taskToAction(task: MidsceneReportTask): { type: string; thought?: string; param: { value?: string; coordinate?: { x: number; y: number }; locate?: { description?: string } } } | null {
    // 提取坐标
    let coordinate: { x: number; y: number } | undefined;
    
    if (task.param?.locate?.center && Array.isArray(task.param.locate.center)) {
      const [x, y] = task.param.locate.center;
      coordinate = { x, y };
    } else if (task.param?.locate?.rect) {
      const rect = task.param.locate.rect;
      coordinate = {
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2,
      };
    }

    return {
      type: task.subType || 'Unknown',
      thought: task.thought,
      param: {
        value: task.param?.value,
        coordinate,
        locate: task.param?.locate,
      },
    };
  }
}

// ============================================================================
// YAML 生成器
// ============================================================================

/**
 * 将 Maestro 命令序列转换为 YAML 格式
 * 
 * @param commands - 命令序列
 * @param appId - 应用包名/Bundle ID
 * @param name - 测试用例名称
 * @param tags - 标签
 * @param platform - 平台配置
 * @returns YAML 字符串
 */
export function generateYaml(
  commands: MaestroCommand[],
  appId: string,
  name?: string,
  tags?: string[],
  platform?: PlatformConfig
): string {
  const lines: string[] = [];

  // 配置部分（在 --- 之前）
  lines.push(`appId: ${appId}`);

  if (name) {
    lines.push(`name: ${name}`);
  }

  if (tags && tags.length > 0) {
    lines.push('tags:');
    for (const tag of tags) {
      lines.push(`  - ${tag}`);
    }
  }

  if (platform) {
    lines.push('platform:');
    if (platform.ios) {
      lines.push('  ios:');
      if (platform.ios.disableAnimations !== undefined) {
        lines.push(`    disableAnimations: ${platform.ios.disableAnimations}`);
      }
    }
    if (platform.android) {
      lines.push('  android:');
      if (platform.android.disableAnimations !== undefined) {
        lines.push(`    disableAnimations: ${platform.android.disableAnimations}`);
      }
    }
  }

  // 分隔符
  lines.push('---');

  // 命令部分（在 --- 之后）
  for (const command of commands) {
    const commandLines = convertCommandToYaml(command);
    lines.push(...commandLines);
  }

  return lines.join('\n');
}

/**
 * 将单个命令转换为 YAML 行
 */
function convertCommandToYaml(command: MaestroCommand): string[] {
  const lines: string[] = [];

  for (const [key, value] of Object.entries(command)) {
    if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
      lines.push(`- ${key}:`);
      for (const [subKey, subValue] of Object.entries(value)) {
        lines.push(`    ${subKey}: ${formatValue(subValue)}`);
      }
    } else if (typeof value === 'string') {
      lines.push(`- ${key}: ${formatValue(value)}`);
    } else if (typeof value === 'number') {
      lines.push(`- ${key}: ${value}`);
    } else {
      lines.push(`- ${key}: ${JSON.stringify(value)}`);
    }
  }

  return lines;
}

/**
 * 格式化值（处理字符串引号）
 */
function formatValue(value: unknown): string {
  if (typeof value === 'string') {
    // 如果字符串包含特殊字符，使用引号
    if (value.includes(':') || value.includes('#') || value.includes(',')) {
      return `"${value}"`;
    }
    return value;
  }
  return String(value);
}

/**
 * 添加注释到 YAML
 * 
 * @param yaml - 原始 YAML
 * @param comments - 注释映射（行号 -> 注释文本）
 * @returns 添加注释后的 YAML
 */
export function addComments(yaml: string, comments: Map<number, string>): string {
  const lines = yaml.split('\n');
  const result: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const comment = comments.get(i);
    if (comment) {
      result.push(`# ${comment}`);
    }
    result.push(lines[i]);
  }

  return result.join('\n');
}
