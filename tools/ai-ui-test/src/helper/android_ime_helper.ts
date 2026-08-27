/**
 * Android 输入法管理工具
 * 提供 Android 输入法的检查、启用、切换等功能
 */

import { executeAdbCommand } from './android_device.js';
import { logger } from './logger.js';

/**
 * 获取当前输入法
 */
export function getCurrentIme(): string | null {
  try {
    const result = executeAdbCommand('shell settings get secure default_input_method', true);
    const ime = result?.trim();
    return ime && ime !== 'null' ? ime : null;
  } catch {
    return null;
  }
}

/**
 * 检查输入法是否已启用
 * 
 * @param imeName - 输入法名称
 */
export function isImeEnabled(imeName: string): boolean {
  try {
    const result = executeAdbCommand('shell ime list -s', true);
    return result.includes(imeName);
  } catch {
    return false;
  }
}

/**
 * 启用输入法
 * 
 * @param imeName - 输入法名称
 */
export function enableIme(imeName: string): void {
  executeAdbCommand(`shell ime enable ${imeName}`, true);
}

/**
 * 设置当前输入法
 * 
 * @param imeName - 输入法名称
 */
export function setIme(imeName: string): void {
  executeAdbCommand(`shell ime set ${imeName}`, true);
}

/**
 * 重置输入法到默认值
 */
export function resetIme(): void {
  executeAdbCommand('shell ime reset', true);
}

/**
 * 检查输入法是否为当前激活的输入法
 * 
 * @param imeName - 输入法名称
 */
export function isImeActive(imeName: string): boolean {
  const currentIme = getCurrentIme();
  return currentIme ? currentIme.includes(imeName) : false;
}

/**
 * 恢复原始输入法
 * 
 * @param imeName - 原始输入法名称（如果提供则恢复到指定输入法，否则使用 ime reset）
 */
export function restoreIme(imeName?: string | null): void {
  try {
    logger.info('正在恢复原始输入法...');
    
    if (imeName) {
      setIme(imeName);
      logger.info(`✓ 已恢复到输入法: ${imeName}`);
    } else {
      resetIme();
      logger.info('✓ 输入法已恢复');
    }
  } catch (error) {
    logger.error('恢复输入法失败:', error);
  }
}