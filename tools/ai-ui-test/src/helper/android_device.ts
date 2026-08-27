/**
 * Android 平台辅助工具
 * 提供 Android 设备操作的通用功能
 */

import { execSync } from 'child_process';
import { join } from 'path';
import { setupAndroidSdkEnvironment } from './android_sdk_locator.js';

/**
 * 缓存的 adb 命令路径
 * 避免频繁查找，提升性能
 */
let cachedAdbPath: string | null = null;

/**
 * 获取 adb 命令路径
 * 优先使用系统 PATH 中的 adb，如果找不到则尝试从 Android SDK 中查找
 * 
 * @returns adb 命令路径，如果找不到返回 null
 */
function getAdbPath(): string | null {
  // 如果已经缓存，直接返回
  if (cachedAdbPath !== null) {
    return cachedAdbPath;
  }

  // 1. 首先尝试使用系统 PATH 中的 adb
  try {
    execSync('adb version', { stdio: 'pipe' });
    cachedAdbPath = 'adb';
    return cachedAdbPath;
  } catch {
    // adb 不在 PATH 中，继续尝试其他方法
  }

  // 2. 尝试通过 Android SDK 查找 adb
  const sdkSetup = setupAndroidSdkEnvironment();
  if (sdkSetup) {
    // SDK 环境设置成功后，adb 应该已经在 PATH 中了
    try {
      execSync('adb version', { stdio: 'pipe' });
      cachedAdbPath = 'adb';
      return cachedAdbPath;
    } catch {
      // 即使设置了 SDK 环境，adb 仍然不可用
    }

    // 3. 最后尝试直接使用 SDK 中的 adb 完整路径
    if (process.env.ANDROID_HOME) {
      const adbPath = join(
        process.env.ANDROID_HOME,
        'platform-tools',
        process.platform === 'win32' ? 'adb.exe' : 'adb'
      );
      try {
        execSync(`"${adbPath}" version`, { stdio: 'pipe' });
        cachedAdbPath = adbPath;
        return cachedAdbPath;
      } catch {
        // adb 路径无效
      }
    }
  }

  // 所有方法都失败，返回 null
  return null;
}

/**
 * 执行 ADB 命令
 * 
 * @param command - ADB 命令（不包含 'adb' 前缀）
 * @param silent - 是否静默执行（不输出到控制台）
 * @returns 命令输出结果
 */
export function executeAdbCommand(command: string, silent: boolean = false): string {
  const adbPath = getAdbPath();
  
  if (!adbPath) {
    throw new Error('ADB 不可用，请确保已安装 Android SDK 并配置环境变量');
  }

  try {
    const result = execSync(`"${adbPath}" ${command}`, {
      encoding: 'utf-8',
      stdio: silent ? 'pipe' : 'inherit'
    });
    return result?.trim() ?? '';
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`ADB 命令执行失败: ${error.message}`);
    }
    throw error;
  }
}

/**
 * 检查 ADB 是否可用
 */
export function isAdbAvailable(): boolean {
  return getAdbPath() !== null;
}

/**
 * 检查 Android 设备是否连接
 */
export function isAndroidDeviceConnected(): boolean {
  try {
    const devices = executeAdbCommand('devices', true);
    const lines = devices.split('\n').filter(line => line.trim() && !line.includes('List of devices'));
    return lines.length > 0;
  } catch {
    return false;
  }
}

/**
 * 获取 Android 设备 ID
 */
export function getAndroidDeviceId(): string | null {
  try {
    const result = executeAdbCommand('get-serialno', true);
    return result.trim();
  } catch {
    return null;
  }
}

/**
 * 检查应用是否已安装
 * 
 * @param packageName - 应用包名
 */
export function isAndroidAppInstalled(packageName: string): boolean {
  try {
    const result = executeAdbCommand(`shell pm list packages ${packageName}`, true);
    return result.includes(packageName);
  } catch {
    return false;
  }
}

/**
 * 安装 APK
 * 
 * @param apkPath - APK 文件路径
 * @param reinstall - 是否重新安装(覆盖已有版本)
 */
export function installAndroidApk(apkPath: string, reinstall: boolean = true): void {
  const flags = reinstall ? '-r' : '';
  executeAdbCommand(`install ${flags} "${apkPath}"`);
}

