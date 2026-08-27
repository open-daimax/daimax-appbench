/**
 * Maestro Android ADBKeyboard 环境准备
 * 专门负责为 Maestro 测试准备 ADBKeyboard 输入法
 */

import { existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { logger } from '../helper/logger.js';
import {
  isAdbAvailable,
  isAndroidDeviceConnected,
  getAndroidDeviceId,
  isAndroidAppInstalled,
  installAndroidApk
} from '../helper/android_device.js';
import {
  getCurrentIme,
  isImeEnabled,
  enableIme,
  setIme,
  isImeActive
} from '../helper/android_ime_helper.js';

// 获取项目根目录
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PROJECT_ROOT = join(__dirname, '..', '..');

/**
 * ADBKeyboard 配置
 */
const ADBKEYBOARD_CONFIG = {
  packageName: 'com.android.adbkeyboard',
  imeName: 'com.android.adbkeyboard/.AdbIME',
  // 克隆修改版，增加了 deeplink 的调用方式，这样才能通过 maestro 的 openLink 命令使用
  // 内置 vendor 目录（不再走网络下载）
  localPath: join(PROJECT_ROOT, 'vendor', 'ADBKeyBoard.apk')
};

/**
 * 环境准备结果
 */
export interface ADBKeyboardSetupResult {
  success: boolean;
  message: string;
  deviceId?: string;
  originalIme?: string | null;
  details?: {
    adbKeyboardInstalled: boolean;
    imeEnabled: boolean;
    imeActivated: boolean;
  };
}

/**
 * 安装 ADBKeyboard（从内置 vendor 目录，不再走网络下载）
 */
async function installAdbKeyboard(): Promise<void> {
  const apkPath = ADBKEYBOARD_CONFIG.localPath;

  // 检查内置 vendor APK 是否存在（文件不存在则报错，不再下载）
  if (!existsSync(apkPath)) {
    throw new Error(`ADBKeyboard APK 不存在: ${apkPath}，请确认 vendor/ADBKeyBoard.apk 已正确内置`);
  }

  logger.info('✓ 使用内置 vendor APK');

  // 安装 APK
  logger.info('正在安装 ADBKeyboard...');
  installAndroidApk(apkPath, true);
  logger.info('✓ 安装完成');
}

/**
 * 准备 ADBKeyboard 环境
 * 
 * @returns 环境准备结果
 */
export async function setupADBKeyboard(): Promise<ADBKeyboardSetupResult> {
  try {
    // 1. 检查 ADB 是否可用
    if (!isAdbAvailable()) {
      return {
        success: false,
        message: 'ADB 未安装或不在 PATH 中，请先安装 Android SDK Platform Tools'
      };
    }

    // 2. 检查 Android 设备是否连接
    if (!isAndroidDeviceConnected()) {
      return {
        success: false,
        message: '未检测到 Android 设备，请确保设备已连接并启用 USB 调试'
      };
    }

    logger.info('✓ ADB 可用，设备已连接');

    // 获取设备 ID
    const deviceId = getAndroidDeviceId();
    if (!deviceId) {
      return {
        success: false,
        message: '无法获取设备 ID'
      };
    }

    logger.info(`✓ 设备 ID: ${deviceId}`);

    // 保存当前输入法
    const originalIme = getCurrentIme();
    if (originalIme) {
      logger.info(`✓ 当前输入法: ${originalIme}`);
    }

    // 3. 检查 ADBKeyboard 是否已安装
    let adbKeyboardInstalled = isAndroidAppInstalled(ADBKEYBOARD_CONFIG.packageName);
    
    if (!adbKeyboardInstalled) {
      logger.info('ADBKeyboard 未安装，开始安装...');
      await installAdbKeyboard();
      adbKeyboardInstalled = true;
    } else {
      logger.info('✓ ADBKeyboard 已安装');
    }

    // 4. 检查输入法是否已启用
    let imeEnabled = isImeEnabled(ADBKEYBOARD_CONFIG.imeName);
    
    if (!imeEnabled) {
      logger.info('正在启用 ADBKeyboard 输入法...');
      enableIme(ADBKEYBOARD_CONFIG.imeName);
      imeEnabled = true;
      logger.info('✓ 输入法已启用');
    } else {
      logger.info('✓ ADBKeyboard 输入法已启用');
    }

    // 5. 检查输入法是否为当前输入法
    let imeActivated = isImeActive(ADBKEYBOARD_CONFIG.imeName);
    
    if (!imeActivated) {
      logger.info('正在切换到 ADBKeyboard 输入法...');
      setIme(ADBKEYBOARD_CONFIG.imeName);
      imeActivated = true;
      logger.info('✓ 输入法已切换');
    } else {
      logger.info('✓ ADBKeyboard 已设为当前输入法');
    }

    return {
      success: true,
      message: 'ADBKeyboard 环境准备完成',
      deviceId,
      originalIme,
      details: {
        adbKeyboardInstalled,
        imeEnabled,
        imeActivated
      }
    };
  } catch (error) {
    return {
      success: false,
      message: error instanceof Error ? error.message : String(error)
    };
  }
}