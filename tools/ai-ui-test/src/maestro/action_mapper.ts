/**
 * Midscene 动作到 Maestro 命令的映射器
 */

import type { MidsceneAction, MaestroCommand, ConversionOptions } from './types.js';
import type { Platform } from '../types.js';
import { logger } from '../helper/logger.js';

/**
 * 内部转换选项（包含从报告中解析的字段）
 */
interface InternalConversionOptions extends ConversionOptions {
  usePercentageCoordinates?: boolean;
  screenSize?: {
    width: number;
    height: number;
  };
  targetPlatform?: Platform;
}

/**
 * 将 Midscene 动作映射为 Maestro 命令
 * 
 * @param action - Midscene 动作
 * @param options - 转换选项（可选，可能包含内部字段）
 * @returns Maestro 命令数组（一个动作可能映射为多个命令）
 */
export function mapActionToCommands(
  action: MidsceneAction,
  options?: InternalConversionOptions
): MaestroCommand[] {
  const commands: MaestroCommand[] = [];

  // 跳过没有参数的动作
  if (!action.param) {
    return commands;
  }

  switch (action.type) {
    case 'Tap':
    case 'Click':
      commands.push(...mapTapAction(action, options));
      break;

    case 'Input':
    case 'Type':
      commands.push(...mapInputAction(action, options));
      break;

    case 'Scroll':
      commands.push(...mapScrollAction(action));
      break;

    case 'Swipe':
      commands.push(...mapSwipeAction(action));
      break;

    case 'Assert':
    case 'AssertVisible':
      commands.push(...mapAssertAction(action));
      break;

    case 'Wait':
      commands.push(...mapWaitAction(action));
      break;

    case 'Sleep':
      commands.push(...mapSleepAction(action));
      break;

    default:
      // 未知动作类型，记录但不转换
      logger.warn(`未知的动作类型: ${action.type}`);
      break;
  }

  return commands;
}

/**
 * 映射点击动作
 */
function mapTapAction(
  action: MidsceneAction,
  options?: InternalConversionOptions
): MaestroCommand[] {
  const commands: MaestroCommand[] = [];

  // 如果启用文本选择器且有描述信息，优先使用文本选择器
  if (options?.preferTextSelectors && action.param?.locate?.description) {
    const description = action.param.locate.description;
    // 提取可能的文本内容（简单处理，提取引号内的文本）
    const textMatch = description.match(/["']([^"']+)["']/);
    if (textMatch) {
      commands.push({
        tapOn: {
          text: textMatch[1]
        }
      });
      return commands;
    }
  }

  // 使用坐标
  let x: number, y: number;

  if (action.param?.coordinate) {
    x = action.param.coordinate.x;
    y = action.param.coordinate.y;
  } else if (action.param?.position) {
    const pos = action.param.position;
    x = pos.left + pos.width / 2;
    y = pos.top + pos.height / 2;
  } else {
    return commands;
  }

  // 转换坐标格式
  const point = formatCoordinate(x, y, options);
  commands.push({
    tapOn: {
      point
    }
  });

  return commands;
}

/**
 * 检查字符串是否为纯 ASCII
 */
function isAsciiOnly(text: string): boolean {
  return /^[\x00-\x7F]*$/.test(text);
}

/**
 * 将文本转换为 Base64 并进行 URL 编码
 */
function toBase64(text: string): string {
  const base64 = Buffer.from(text, 'utf-8').toString('base64');
  // URL 编码 Base64 字符串，避免 = 号等特殊字符导致问题
  return encodeURIComponent(base64);
}

/**
 * 映射输入动作
 */
function mapInputAction(
  action: MidsceneAction,
  options?: InternalConversionOptions
): MaestroCommand[] {
  const commands: MaestroCommand[] = [];

  // 如果有位置信息，先点击输入框
  if (action.param?.coordinate || action.param?.position) {
    commands.push(...mapTapAction(action, options));
  }

  // 输入文本
  if (action.param?.value) {
    const text = action.param.value;
    const targetPlatform = options?.targetPlatform || 'android';
    
    // iOS 平台始终使用 inputText
    if (targetPlatform === 'ios') {
      commands.push({
        inputText: text
      });
    } else if (targetPlatform === 'android') {
      // Android 平台：ASCII 使用 inputText，非 ASCII 使用 openLink + Base64
      if (isAsciiOnly(text)) {
        commands.push({
          inputText: text
        });
      } else {
        // 包含非 ASCII 字符（如中文），使用 openLink + Base64
        const base64Text = toBase64(text);
        commands.push({
          openLink: `adbkeyboard://input?b64=${base64Text}`
        });
      }
    } else {
      // 其他平台默认使用 inputText
      commands.push({
        inputText: text
      });
    }
  }

  return commands;
}

/**
 * 映射滚动动作
 */
function mapScrollAction(action: MidsceneAction): MaestroCommand[] {
  const commands: MaestroCommand[] = [];

  // 根据参数判断滚动方向
  const direction = action.param?.value?.toLowerCase() || 'down';

  commands.push({
    scroll: {
      direction: direction
    }
  });

  return commands;
}

/**
 * 映射滑动动作
 */
function mapSwipeAction(action: MidsceneAction): MaestroCommand[] {
  const commands: MaestroCommand[] = [];

  // 根据参数判断滑动方向
  const direction = action.param?.value?.toLowerCase() || 'up';

  commands.push({
    swipe: {
      direction: direction
    }
  });

  return commands;
}

/**
 * 映射断言动作
 */
function mapAssertAction(action: MidsceneAction): MaestroCommand[] {
  const commands: MaestroCommand[] = [];

  // 如果有描述文本，使用 assertVisible
  if (action.thought) {
    commands.push({
      assertVisible: action.thought
    });
  }

  return commands;
}

/**
 * 映射等待动作
 */
function mapWaitAction(action: MidsceneAction): MaestroCommand[] {
  const commands: MaestroCommand[] = [];

  // 如果有描述文本，使用 extendedWaitUntil
  if (action.thought) {
    commands.push({
      extendedWaitUntil: {
        visible: action.thought,
        timeout: 10000 // 默认 10 秒超时
      }
    });
  }

  return commands;
}

/**
 * 映射睡眠/延迟动作
 */
function mapSleepAction(action: MidsceneAction): MaestroCommand[] {
  const commands: MaestroCommand[] = [];

  // 从参数中提取延迟时间（毫秒）
  let timeoutMs = 5000; // 默认 5 秒

  if (action.param?.value) {
    const value = action.param.value;
    // 尝试解析数字
    const parsed = parseInt(value, 10);
    if (!isNaN(parsed)) {
      timeoutMs = parsed;
    }
  }

  // 使用 waitForAnimationToEnd 等待动画结束
  commands.push({
    waitForAnimationToEnd: {
      timeout: timeoutMs
    }
  });

  return commands;
}

/**
 * 格式化坐标
 * 
 * @param x - X 坐标
 * @param y - Y 坐标
 * @param options - 转换选项（包含内部字段）
 * @returns 格式化后的坐标字符串
 */
function formatCoordinate(
  x: number,
  y: number,
  options?: InternalConversionOptions
): string {
  // 如果启用百分比坐标且提供了屏幕尺寸
  if (options?.usePercentageCoordinates && options.screenSize) {
    const { width, height } = options.screenSize;
    // Maestro 要求百分比坐标必须是整数
    const xPercent = Math.round((x / width) * 100);
    const yPercent = Math.round((y / height) * 100);
    return `${xPercent}%,${yPercent}%`;
  }

  // 默认使用绝对坐标
  return `${Math.round(x)},${Math.round(y)}`;
}

/**
 * 过滤和优化命令序列
 * 
 * @param commands - 原始命令序列
 * @returns 优化后的命令序列
 */
export function optimizeCommands(commands: MaestroCommand[]): MaestroCommand[] {
  const optimized: MaestroCommand[] = [];

  for (let i = 0; i < commands.length; i++) {
    const cmd = commands[i];

    // 移除连续的重复命令
    if (i > 0 && JSON.stringify(cmd) === JSON.stringify(commands[i - 1])) {
      continue;
    }

    optimized.push(cmd);
  }

  return optimized;
}