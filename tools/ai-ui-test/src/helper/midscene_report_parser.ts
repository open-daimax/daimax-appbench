/**
 * Midscene 报告解析器
 * 
 * 用于解析 Midscene 生成的 HTML 测试报告，提取关键信息
 */

import { readFile } from 'fs/promises';
import { existsSync, mkdirSync, writeFileSync } from 'fs';
import { dirname } from 'path';
import { logger } from './logger.js';

/**
 * Midscene 报告数据结构
 */
interface MidsceneReport {
  sdkVersion: string;
  groupName: string;
  groupDescription: string;
  modelBriefs: unknown[];
  executions: MidsceneExecution[];
}

/** 支持的 schema 版本范围 */
const SUPPORTED_SDK_VERSIONS = ['0.', '1.', '2.'];

/**
 * 执行记录
 */
interface MidsceneExecution {
  logTime: number;
  name: string;
  tasks: MidsceneTask[];
}

/**
 * 任务记录
 */
interface MidsceneTask {
  status: string;
  type: string;
  subType?: string;
  param?: {
    dataDemand?: string;
    locate?: {
      description?: string;
      center?: number[];
      rect?: { left: number; top: number; width: number; height: number };
    };
    value?: string;
  };
  thought?: string;
  reasoning_content?: string;
  error?: string | null;
  output?: MidsceneTaskOutput;
  uiContext?: {
    shotSize?: { width: number; height: number };
  };
}

/**
 * 任务输出结构
 */
type MidsceneTaskOutput = boolean | string | {
  thought?: string;
  output?: string;
  actions?: MidsceneTaskAction[];
} | undefined;

/**
 * 任务动作
 */
interface MidsceneTaskAction {
  type: string;
  param?: {
    value?: string;
    locate?: {
      description?: string;
    };
  };
}

/**
 * 从 HTML 报告文件中提取 JSON 数据（从后向前查找，只查找第一个结果）
 * 
 * @param reportPath - 报告文件路径
 * @returns 解析后的报告数据
 */
async function extractReportData(reportPath: string): Promise<MidsceneReport | null> {
  try {
    // 读取文件内容
    const content = await readFile(reportPath, 'utf-8');
    
    // 从后向前查找 <script type="midscene_web_dump"> 标签
    // 使用 lastIndexOf 找到最后一个标签的位置
    const scriptStartTag = '<script type="midscene_web_dump">';
    const scriptEndTag = '</script>';
    
    const lastStartIndex = content.lastIndexOf(scriptStartTag);
    if (lastStartIndex === -1) {
      return null;
    }
    
    // 从最后一个开始标签位置开始查找结束标签
    const jsonStartIndex = lastStartIndex + scriptStartTag.length;
    const jsonEndIndex = content.indexOf(scriptEndTag, jsonStartIndex);
    
    if (jsonEndIndex === -1) {
      return null;
    }
    
    // 提取 JSON 字符串
    const jsonStr = content.substring(jsonStartIndex, jsonEndIndex);
    
    // 解析 JSON
    const data = JSON.parse(jsonStr) as MidsceneReport;

    // Schema 版本校验：记录版本信息用于调试，不兼容时发出警告
    if (data.sdkVersion) {
      const isSupported = SUPPORTED_SDK_VERSIONS.some(prefix => data.sdkVersion.startsWith(prefix));
      if (!isSupported) {
        logger.warn(
          `[midscene_report_parser] 未知的 sdkVersion: ${data.sdkVersion}，` +
          `支持的版本前缀: ${SUPPORTED_SDK_VERSIONS.join(', ')}。解析结果可能不可靠。`
        );
      }
    }

    return data;
  } catch (error) {
    // 解析失败时返回 null，不抛出异常
    return null;
  }
}

/**
 * 报告数据缓存（避免重复解析同一个文件）
 */
const reportCache = new Map<string, MidsceneReport | null>();

/**
 * 获取报告数据（带缓存）
 * 
 * @param reportPath - 报告文件路径
 * @returns 解析后的报告数据
 */
async function getReportData(reportPath: string): Promise<MidsceneReport | null> {
  // 检查缓存
  if (reportCache.has(reportPath)) {
    return reportCache.get(reportPath) || null;
  }
  
  // 解析并缓存
  const report = await extractReportData(reportPath);
  reportCache.set(reportPath, report);
  
  return report;
}

/**
 * 从报告中提取 Assert 步骤的 thought
 * 
 * @param reportPath - 报告文件路径
 * @returns Assert 步骤的 thought 内容，如果未找到则返回 undefined
 */
export async function extractAssertThought(reportPath: string): Promise<string | undefined> {
  const report = await getReportData(reportPath);
  
  if (!report) {
    return undefined;
  }
  
  // 从后向前查找 Assert 类型的执行记录（通常 Assert 在最后）
  for (let i = report.executions.length - 1; i >= 0; i--) {
    const execution = report.executions[i];
    
    // 检查执行名称是否包含 "Assert"
    if (execution.name.includes('Assert')) {
      // 从后向前查找 Assert 类型的任务
      for (let j = execution.tasks.length - 1; j >= 0; j--) {
        const task = execution.tasks[j];
        if (task.subType === 'Assert' && task.thought) {
          return task.thought;
        }
      }
    }
  }
  
  return undefined;
}

/**
 * 清除报告缓存（可选，用于释放内存）
 * 
 * @param reportPath - 报告文件路径，如果不提供则清除所有缓存
 */
export function clearReportCache(reportPath?: string): void {
  if (reportPath) {
    reportCache.delete(reportPath);
  } else {
    reportCache.clear();
  }
}

/**
 * 操作类型中文映射
 */
const ACTION_TYPE_MAP: Record<string, string> = {
  Tap: '点击',
  Input: '输入',
  Sleep: '等待',
  Scroll: '滚动',
  Back: '返回',
  Home: '主页',
  KeyboardPress: '按键',
};

/**
 * 从 task 中提取最佳 thought（取 thought 和 reasoning_content 中更长的那个）
 */
function pickThought(rawTask: MidsceneTask): string {
  const outputObj = rawTask.output;
  const t1 = (typeof outputObj === 'object' && outputObj !== null && !Array.isArray(outputObj) && 'thought' in outputObj)
    ? (outputObj as { thought?: string }).thought || ''
    : (rawTask.thought || '');
  const t2 = rawTask.reasoning_content || '';
  return t1.length >= t2.length ? t1 : t2;
}

/**
 * 从报告中提取执行链路，输出为精简 Markdown 格式
 * 
 * @param reportPath - 报告文件路径
 * @returns Markdown 格式的执行链路文本，如果解析失败则返回 null
 */
export async function extractExecutionChain(reportPath: string): Promise<string | null> {
  const report = await getReportData(reportPath);
  
  if (!report) {
    return null;
  }

  const lines: string[] = [];

  for (const execution of report.executions) {
    // 判断是 act 还是 assert
    const isAssert = execution.name.includes('Assert');
    
    if (isAssert) {
      // Assert 执行：提取断言名称（去掉 "Assert - " 前缀）
      const assertName = execution.name.replace(/^Assert\s*-\s*/, '');
      lines.push(`# 断言: ${assertName}`);
      
      // 查找 Assert 类型的 task
      for (const task of execution.tasks) {
        if (task.subType === 'Assert') {
          const passed = task.output === true;
          lines.push(`结果: ${passed ? '✓ 通过' : '✗ 失败'}`);
          
          // 提取 thought
          const thought = pickThought(task);
          if (thought) {
            lines.push(`> ${thought.replace(/\n/g, '\n> ')}`);
          }
        }
      }
      lines.push('');
    } else {
      // Act 执行：提取操作名称（去掉 "Act - " 前缀）
      const actName = execution.name.replace(/^Act\s*-\s*/, '');
      lines.push(`# 操作: ${actName}`);
      lines.push('');
      
      let stepNum = 0;
      
      for (const task of execution.tasks) {
        // 只处理 Plan 步骤，跳过其他所有步骤
        if (task.subType !== 'Plan') {
          continue;
        }
        
        const thought = pickThought(task);
        const outputObj = task.output;
        const actions: MidsceneTaskAction[] = (typeof outputObj === 'object' && outputObj !== null && !Array.isArray(outputObj) && 'actions' in outputObj)
          ? ((outputObj as { actions?: MidsceneTaskAction[] }).actions || [])
          : [];
        const isFailed = task.status !== 'finished';
        const failMark = isFailed ? ' (失败)' : '';
        
        if (actions.length === 0) {
          // 最后一个 Plan（无 actions，任务完成）
          const completionOutput = (typeof outputObj === 'object' && outputObj !== null && !Array.isArray(outputObj) && 'output' in outputObj)
            ? (outputObj as { output?: string }).output
            : undefined;
          const completionMsg = completionOutput || thought || '任务完成';
          // 取第一句话作为摘要
          const summary = completionMsg.split(/[。\n]/)[0];
          stepNum++;
          lines.push(`${stepNum}. [完成] ${summary}${failMark}`);
        } else {
          // 有 actions 的 Plan 步骤
          for (const action of actions) {
            stepNum++;
            const actionLabel = ACTION_TYPE_MAP[action.type] || action.type;
            let stepTitle = `[${actionLabel}]`;
            
            // 添加操作目标/值
            if (action.type === 'Tap' && action.param?.locate?.description) {
              stepTitle += ` ${action.param.locate.description}`;
            } else if (action.type === 'Input' && action.param?.value) {
              stepTitle += ` "${action.param.value}"`;
            }
            
            lines.push(`${stepNum}. ${stepTitle}${failMark}`);
          }
          
          // 添加 thought 引用块
          if (thought) {
            lines.push(`   > ${thought.replace(/\n/g, '\n   > ')}`);
          }
        }
        
        lines.push('');
      }
    }
  }

  return lines.join('\n').trim() || null;
}

/**
 * 从报告中提取步骤执行失败的原因
 *
 * 当 UI 操作步骤失败时（如 replan 超限），提取 AI 最后一次 Plan 步骤的 thought，
 * 其中包含了 AI 对当前页面状态的观察和分析，比原始错误信息更有价值。
 *
 * @param reportPath - 报告文件路径
 * @returns 失败原因描述，如果未找到则返回 undefined
 */
export async function extractFailureReason(reportPath: string): Promise<string | undefined> {
  const report = await getReportData(reportPath);

  if (!report) {
    return undefined;
  }

  // 从后向前查找 Act 类型的执行记录，取最后一个 Plan 步骤的 thought
  for (let i = report.executions.length - 1; i >= 0; i--) {
    const execution = report.executions[i];

    // 跳过 Assert 类型的执行
    if (execution.name.includes('Assert')) {
      continue;
    }

    // 从后向前查找 Plan 类型的 task
    for (let j = execution.tasks.length - 1; j >= 0; j--) {
      const task = execution.tasks[j];
      if (task.subType === 'Plan') {
        const thought = pickThought(task);
        if (thought) {
          return thought.trim();
        }
      }
    }
  }

  return undefined;
}

/**
 * 保存执行链路到指定文件
 *
 * @param content - Markdown 格式的执行链路内容
 * @param filePath - 目标文件路径
 * @returns 保存的文件绝对路径
 */
export function saveExecutionChain(content: string, filePath: string): string {
  const dir = dirname(filePath);
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }
  writeFileSync(filePath, content, 'utf-8');
  return filePath;
}
