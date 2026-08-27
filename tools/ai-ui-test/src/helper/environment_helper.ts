import { execSync } from 'child_process';
import { getConnectedDevices as getAndroidDevices } from '@midscene/android';
// @ts-ignore - Harmony 模块可能未安装
import { getConnectedDevices as getHarmonyDevices } from '@midscene/harmony';
import { isAdbAvailable } from './android_device.js';
import { IOSHelper } from './ios_helper.js';
import { logger } from './logger.js';
import { ReturnAsResultError } from '../types.js';

// ============================================================================
// PATH 初始化
// ============================================================================

/**
 * 从用户的登录 shell 中加载完整的 PATH
 * 解决 Node.js 子进程无法继承 .zshrc 等配置中 PATH 修改的问题
 */
function loadShellPath(): void {
  try {
    const shell = process.env.SHELL || '/bin/sh';
    const fullPath = execSync(`${shell} -l -c 'echo $PATH'`, { encoding: 'utf-8', timeout: 5000 }).trim();
    if (fullPath) {
      process.env.PATH = fullPath;
    }
  } catch {
    // 静默失败，使用默认 PATH
  }

  // 兜底：如果 HDC_HOME 已设置但不在 PATH 中，自动补充
  const hdcHome = process.env.HDC_HOME;
  if (hdcHome && !process.env.PATH?.includes(hdcHome)) {
    process.env.PATH = `${hdcHome}:${process.env.PATH || ''}`;
  }
}

// 模块加载时立即执行，确保所有后续命令检查都能找到正确的 PATH
loadShellPath();

/**
 * 设备信息接口
 */
export interface DeviceInfo {
  platform: 'android' | 'harmony' | 'ios' | 'web';
  deviceId: string;
}

// ============================================================================
// 环境检查
// ============================================================================

/**
 * 检查命令是否可用
 */
function isCommandAvailable(command: string): boolean {
  try {
    execSync(`which ${command}`, { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

/**
 * 检查 Android 环境
 */
function checkAndroidEnvironment(): { available: boolean; message: string } {
  // 检查 adb 是否可用（getAdbPath 内部会在需要时自动尝试从 SDK 查找）
  if (!isAdbAvailable()) {
    return {
      available: false,
      message: '⚠ adb 命令不可用，请安装 Android SDK'
    };
  }
  
  return {
    available: true,
    message: '✓ adb 命令可用'
  };
}

/**
 * 检查 Harmony 环境
 */
function checkHarmonyEnvironment(): { available: boolean; message: string } {
  if (!isCommandAvailable('hdc')) {
    return {
      available: false,
      message: '⚠ hdc 命令不可用'
    };
  }
  return {
    available: true,
    message: '✓ hdc 命令可用'
  };
}

/**
 * 检查 Web 浏览器环境
 */
function checkWebBrowser(): { available: boolean; message: string } {
  // Web 平台总是可用（使用 Playwright）
  return {
    available: true,
    message: '✓ Web 浏览器可用 (Playwright)',
  };
}

/**
 * 检查平台环境
 * 
 * @param platform - 平台类型，如果不指定则检查所有平台
 */
export function checkPlatformEnvironment(
  platform?: 'android' | 'ios' | 'harmony' | 'web' | 'expo_android' | 'expo_ios'
): void {
  if (!platform) {
    // 检查所有平台
    const androidCheck = checkAndroidEnvironment();
    const harmonyCheck = checkHarmonyEnvironment();
    const webCheck = checkWebBrowser();
    
    logger.info(androidCheck.message);
    logger.info(harmonyCheck.message);
    logger.info(webCheck.message);
    return;
  }
  
  // 检查指定平台
  let result: { available: boolean; message: string } | undefined;
  
  switch (platform) {
    case 'android':
    case 'expo_android':
      result = checkAndroidEnvironment();
      break;
    case 'harmony':
      result = checkHarmonyEnvironment();
      break;
    case 'web':
      result = checkWebBrowser();
      break;
    case 'ios':
    case 'expo_ios':
      // iOS 主要依赖 WebDriverAgent，在设备检测时检查
      return;
  }
  
  if (result) {
    logger.info(result.message);
    
    if (!result.available) {
      logger.warn(`${platform} 环境不可用，设备检测可能失败`);
    }
  }
}

// ============================================================================
// 设备检测
// ============================================================================

/**
 * WebDriverAgent 状态响应接口
 */
interface WDAStatusResponse {
  value: {
    build: {
      version: string;
      time: string;
      productBundleIdentifier: string;
    };
    os: {
      testmanagerdVersion: number;
      name: string;
      sdkVersion: string;
      version: string;
    };
    device: string;
    ios: {
      ip: string;
    };
    message: string;
    state: string;
    ready: boolean;
  };
  sessionId: string;
}

/**
 * 获取 iOS 设备列表
 * 先检查是否已有 WDA 运行，如果没有则尝试初始化
 * 
 * @param throwOnTimeout 是否在 WDA 启动超时时抛出异常（默认 false）
 * @returns iOS 设备信息数组
 */
async function getIOSDevices(throwOnTimeout: boolean = false, preferSimulator: boolean = false): Promise<DeviceInfo[]> {
  const iosDeviceInfo: DeviceInfo = {
    platform: 'ios',
    deviceId: 'localhost:8100',
  };

  try {
    // 先检查是否已有 WDA 运行
    const statusUrl = 'http://localhost:8100/status';
    const response = await fetch(statusUrl, {
      method: 'GET',
      signal: AbortSignal.timeout(3000),
    });

    if (response.ok) {
      const data = await response.json() as WDAStatusResponse;
      if (data.value && data.value.ready && data.value.state === 'success') {
        logger.debug('检测到已运行的 WDA');
        return [iosDeviceInfo];
      }
    }
  } catch (error) {
    // WDA 未运行，尝试初始化
    logger.info('未检测到运行的 WDA，开始初始化 iOS 设备...');
  }

  // 如果没有运行的 WDA，尝试初始化
  // ReturnAsResultError 会自动向上传播，不需要特殊处理
  const success = await IOSHelper.initializeDevice(undefined, throwOnTimeout, preferSimulator);
  if (success) {
    logger.info('iOS 设备初始化成功');
    return [iosDeviceInfo];
  } else {
    logger.warn('iOS 设备初始化失败');
    return [];
  }
}

/**
 * 获取第一个可用的设备信息
 * 优先级顺序：Android → Harmony → iOS → Web
 * 
 * @param platform - 可选的平台过滤，如果指定则只返回该平台的设备
 * @param deviceId - 可选的设备 ID，如果指定则返回该特定设备
 * @returns 第一个可用设备的信息，如果没有可用设备则返回 null
 */
export async function getFirstAvailableDevice(
  platform?: 'android' | 'ios' | 'harmony' | 'web' | 'expo_android' | 'expo_ios',
  deviceId?: string
): Promise<DeviceInfo | null> {
  // 将 Expo 平台映射到原生平台
  const normalizedPlatform = platform === 'expo_android' ? 'android'
    : platform === 'expo_ios' ? 'ios'
    : platform;

  // 如果指定了设备 ID，尝试直接返回该设备
  if (deviceId) {
    // 如果同时指定了平台，直接返回
    if (normalizedPlatform) {
      return { platform: normalizedPlatform, deviceId };
    }
    
    // 如果只指定了设备 ID，需要推断平台
    // iOS 设备 ID 格式为 "host:port"
    if (deviceId.includes(':')) {
      return { platform: 'ios', deviceId };
    }
    
    // 尝试在各平台中查找该设备
    const allDevices = await getAllAvailableDevices();
    const foundDevice = allDevices.find(d => d.deviceId === deviceId);
    if (foundDevice) {
      return foundDevice;
    }
    
    // 如果找不到该设备，返回 null
    // 调用方应该处理设备未找到的情况
    return null;
  }

  // 如果指定了 web 平台，直接返回 web 设备
  if (normalizedPlatform === 'web') {
    return {
      platform: 'web',
      deviceId: 'browser',
    };
  }

  // 确定要检查的平台列表
  // 如果指定了平台，只检查该平台；否则按优先级检查所有平台
  const platformsToCheck: Array<'android' | 'harmony' | 'ios'> = normalizedPlatform 
    ? [normalizedPlatform] 
    : ['android', 'harmony', 'ios'];

  // 按顺序检查每个平台
  for (const platformName of platformsToCheck) {
    let device: DeviceInfo | null = null;
    
    try {
      switch (platformName) {
        case 'android': {
          const androidDevices = await getAndroidDevices();
          if (androidDevices && androidDevices.length > 0) {
            device = {
              platform: 'android',
              deviceId: androidDevices[0].udid,
            };
          }
          break;
        }
        
        case 'harmony': {
          const harmonyDevices = await getHarmonyDevices();
          if (harmonyDevices && harmonyDevices.length > 0) {
            device = {
              platform: 'harmony',
              deviceId: harmonyDevices[0].deviceId,
            };
          }
          break;
        }
        
        case 'ios': {
          // 如果明确指定了 iOS 平台，在 WDA 超时时抛出详细异常
          // ReturnAsResultError 会自动向上传播
          const shouldThrowOnTimeout = platform === 'ios' || platform === 'expo_ios';
          const shouldPreferSimulator = platform === 'expo_ios';
          const iosDevices = await getIOSDevices(shouldThrowOnTimeout, shouldPreferSimulator);
          if (iosDevices.length > 0) {
            device = iosDevices[0];
          }
          break;
        }
      }
      
      // 如果找到设备，直接返回
      if (device) {
        return device;
      }
    } catch (error) {
      // ReturnAsResultError 直接向上传播，不做处理
      if (error instanceof ReturnAsResultError) {
        throw error;
      }
      // 其他错误（如网络问题、设备断开等）只记录日志，继续尝试下一个平台
      logger.debug(`Failed to get ${platformName} devices: ${error}`);
    }
  }

  return null;
}

/**
 * 获取所有可用的设备列表
 * 
 * @returns 所有可用设备的信息数组
 */
export async function getAllAvailableDevices(): Promise<DeviceInfo[]> {
  const devices: DeviceInfo[] = [];

  // 获取 Android 设备
  try {
    const androidDevices = await getAndroidDevices();
    if (androidDevices && androidDevices.length > 0) {
      devices.push(
        ...androidDevices.map((device) => ({
          platform: 'android' as const,
          deviceId: device.udid,
        }))
      );
    }
  } catch (error) {
    logger.debug(`Failed to get Android devices: ${error}`);
  }

  // 获取 Harmony 设备
  try {
    const harmonyDevices = await getHarmonyDevices();
    if (harmonyDevices && harmonyDevices.length > 0) {
      devices.push(
        ...harmonyDevices.map((device: { deviceId: string }) => ({
          platform: 'harmony' as const,
          deviceId: device.deviceId,
        }))
      );
    }
  } catch (error) {
    logger.debug(`Failed to get Harmony devices: ${error}`);
  }

  // 检查 iOS 设备
  try {
    const iosDevices = await getIOSDevices();
    if (iosDevices && iosDevices.length > 0) {
      devices.push(...iosDevices);
    }
  } catch (error) {
    logger.debug(`Failed to get iOS devices: ${error}`);
  }

  return devices;
}
