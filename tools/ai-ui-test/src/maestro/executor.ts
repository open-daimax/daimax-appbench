/**
 * Maestro 测试执行器
 * 负责完整的测试执行流程：环境准备 → 执行测试 → 环境恢复
 */

import { execSync } from 'child_process';
import { existsSync, mkdirSync } from 'fs';
import { dirname } from 'path';
import { logger } from '../helper/logger.js';
import { getFirstAvailableDevice } from '../helper/environment_helper.js';
import { restoreIme } from '../helper/android_ime_helper.js';
import { setupADBKeyboard } from './android_adbkeyboard.js';
import { convertHtmlToYaml } from './index.js';
import { ErrorType, type TestCase, type TestResult } from '../types.js';

/**
 * 环境准备结果
 */
interface EnvPrepareResult {
  platform: 'android' | 'ios';
  deviceId: string;
  originalIme?: string | null;
}

/**
 * Maestro 执行错误类型
 */
export enum MaestroErrorType {
  /** 测试断言或步骤失败（退出码 1） */
  TEST_FAILURE = 'TEST_FAILURE',
  /** 执行超时 */
  TIMEOUT = 'TIMEOUT',
  /** 进程被外部终止 */
  KILLED = 'KILLED',
  /** Maestro 自身崩溃 */
  CRASH = 'CRASH',
  /** 未知错误 */
  UNKNOWN = 'UNKNOWN',
}

/**
 * 从 execSync 错误中分类 Maestro 错误类型
 */
function classifyMaestroError(error: unknown): { type: MaestroErrorType; message: string } {
  if (error && typeof error === 'object' && 'status' in error) {
    const exitCode = (error as { status: number | null }).status;
    const stderr = 'stderr' in error ? String((error as { stderr?: unknown }).stderr || '') : '';
    
    if (exitCode === null) {
      // 进程被信号终止（超时或外部 kill）
      if (error instanceof Error && error.message.includes('ETIMEDOUT')) {
        return { type: MaestroErrorType.TIMEOUT, message: 'Maestro 测试执行超时' };
      }
      return { type: MaestroErrorType.KILLED, message: 'Maestro 进程被外部终止' };
    } else if (exitCode === 1) {
      return { type: MaestroErrorType.TEST_FAILURE, message: 'Maestro 测试断言失败或步骤执行出错' };
    } else if (exitCode > 1) {
      return { type: MaestroErrorType.CRASH, message: `Maestro 进程异常退出，退出码: ${exitCode}${stderr ? `, stderr: ${stderr.substring(0, 200)}` : ''}` };
    }
  }
  
  if (error instanceof Error && error.message.includes('ETIMEDOUT')) {
    return { type: MaestroErrorType.TIMEOUT, message: 'Maestro 测试执行超时' };
  }
  
  return { 
    type: MaestroErrorType.UNKNOWN, 
    message: error instanceof Error ? error.message : String(error) 
  };
}

/**
 * 检查 Maestro 是否已安装
 */
export function checkMaestroInstalled(): boolean {
  try {
    execSync('maestro --version', { stdio: 'pipe' });
    return true;
  } catch {
    return false;
  }
}

/**
 * 自动安装 Maestro
 * @returns 安装是否成功
 */
export function installMaestro(): boolean {
  logger.info('正在自动安装 Maestro...');
  logger.info('执行命令: curl -fsSL "https://get.maestro.mobile.dev" | bash');
  
  try {
    // 使用 inherit 让用户能看到安装过程的输出
    execSync('curl -fsSL "https://get.maestro.mobile.dev" | bash', {
      stdio: 'inherit',
      shell: '/bin/bash'
    });
    
    logger.info('Maestro 安装命令执行完成，正在验证安装...');
    return true;
  } catch (error) {
    logger.error('Maestro 安装失败', error instanceof Error ? error.message : error);
    return false;
  }
}

/**
 * 确保 Maestro 已安装，如果未安装则自动安装
 * @returns Maestro 是否可用
 */
export function ensureMaestroInstalled(): boolean {
  // 首次检查
  if (checkMaestroInstalled()) {
    logger.debug('Maestro 已安装');
    return true;
  }
  
  logger.warn('Maestro 未安装，将自动进行安装...');
  
  // 尝试安装
  if (!installMaestro()) {
    logger.error('Maestro 自动安装失败');
    return false;
  }
  
  // 安装后重新检查
  if (checkMaestroInstalled()) {
    logger.info('✓ Maestro 安装成功');
    return true;
  }
  
  // 安装后仍然找不到，可能需要重新加载 shell 环境
  logger.error('Maestro 安装后仍无法找到，请尝试重新打开终端或手动执行: source ~/.bashrc 或 source ~/.zshrc');
  logger.error('安装指南: https://docs.maestro.dev/maestro-cli/how-to-install-maestro-cli#macos');
  return false;
}

/**
 * 准备 Maestro 测试环境
 * 
 * @param platform - 可选的平台参数，如果指定则使用该平台，否则自动检测
 * @returns 环境准备结果
 */
async function prepareMaestroEnvironment(
  platform?: 'android' | 'ios'
): Promise<EnvPrepareResult> {
  // 1. 确定平台
  let detectedPlatform: 'android' | 'ios';
  let deviceId: string;
  
  if (platform) {
    // 使用指定的平台
    logger.info(`\n使用指定平台: ${platform}\n`);
    
    const device = await getFirstAvailableDevice(platform);
    if (!device) {
      throw new Error(`未检测到 ${platform} 设备`);
    }
    
    detectedPlatform = platform;
    deviceId = device.deviceId;
    logger.info(`设备 ID: ${deviceId}`);
  } else {
    // 自动检测平台（优先 Android）
    logger.info('正在检测设备...');
    
    const androidDevice = await getFirstAvailableDevice('android');
    if (androidDevice) {
      detectedPlatform = 'android';
      deviceId = androidDevice.deviceId;
      logger.info(`\n检测到 Android 设备: ${deviceId}\n`);
    } else {
      const iosDevice = await getFirstAvailableDevice('ios');
      if (iosDevice) {
        detectedPlatform = 'ios';
        deviceId = iosDevice.deviceId;
        logger.info(`\n检测到 iOS 设备: ${deviceId}\n`);
      } else {
        throw new Error('未检测到支持的设备平台（Android/iOS）');
      }
    }
  }

  // 2. 准备平台特定环境
  let originalIme: string | null = null;
  
  if (detectedPlatform === 'android') {
    logger.info('=== 准备 Android 测试环境 ===\n');
    const envResult = await setupADBKeyboard();
    
    if (!envResult.success) {
      throw new Error(`环境准备失败: ${envResult.message}`);
    }

    originalIme = envResult.originalIme || null;
    logger.info('\n' + envResult.message + '\n');
  } else {
    logger.info('=== iOS 平台无需环境准备 ===\n');
  }

  return {
    platform: detectedPlatform,
    deviceId,
    originalIme
  };
}

/**
 * 执行 Maestro 测试
 * 
 * @param yamlPath - YAML 测试文件路径
 * @param platform - 可选的平台参数，如果指定则使用该平台，否则自动检测
 * @returns 测试是否成功
 */
export async function runMaestroTest(
  yamlPath: string,
  platform?: 'android' | 'ios'
): Promise<boolean> {
  let envResult: EnvPrepareResult | null = null;
  
  try {
    // 1. 检查 Maestro 是否安装，如果未安装则自动安装
    if (!ensureMaestroInstalled()) {
      return false;
    }

    // 2. 准备环境
    envResult = await prepareMaestroEnvironment(platform);

    // 3. 执行 Maestro 测试（细粒度错误处理）
    logger.info('=== 开始执行测试 ===\n');
    try {
      execSync(`maestro test "${yamlPath}"`, { 
        stdio: 'inherit',
        timeout: 300000, // 5分钟超时
      });
    } catch (execError: unknown) {
      const classified = classifyMaestroError(execError);
      logger.error(`Maestro 执行失败 [${classified.type}]: ${classified.message}`);
      return false;
    }
    
    logger.info('\n✓ 测试执行完成');
    return true;
  } catch (error) {
    logger.error('测试执行失败', error instanceof Error ? error.message : error);
    return false;
  } finally {
    // 4. 恢复环境（仅 Android 需要恢复输入法）
    if (envResult?.platform === 'android' && envResult.originalIme) {
      restoreIme(envResult.originalIme);
    }
  }
}

/**
 * 检查是否存在 Maestro YAML 文件
 * 
 * @param yamlPath - YAML 文件完整路径
 * @returns YAML 文件路径，如果不存在则返回 null
 */
export function checkMaestroYaml(yamlPath: string): string | null {
  if (existsSync(yamlPath)) {
    logger.debug(`找到 Maestro YAML 文件: ${yamlPath}`);
    return yamlPath;
  }
  
  logger.debug(`未找到 Maestro YAML 文件: ${yamlPath}`);
  return null;
}

/**
 * 使用 Maestro 执行测试（返回标准测试结果）
 * 
 * @param yamlPath - YAML 文件路径
 * @param platform - 可选的平台参数
 * @returns 测试结果
 * 
 * TODO: Maestro 执行路径目前未集成日志和性能采集。
 * 原因：Maestro 的 execSync 执行方式无法获取测试用例的 packageName 参数，
 * 而性能采集需要 packageName 来监控特定应用的资源使用。
 * 如果后续需要支持，可以：
 * 1. 将 TestCase 作为参数传入此函数
 * 2. 在调用处（executeMaestroWithAssertion）层面集成日志/性能采集
 */
export async function executeMaestroTest(
  yamlPath: string,
  platform?: 'android' | 'ios'
): Promise<TestResult> {
  const startTime = Date.now();
  
  try {
    logger.info('使用 Maestro 执行测试...');
    const success = await runMaestroTest(yamlPath, platform);
    
    const duration = Date.now() - startTime;
    
    if (success) {
      return {
        success: true,
        reason: 'Maestro 测试执行成功',
        duration,
      };
    } else {
      return {
        success: false,
        error: 'Maestro 测试执行失败',
        errorType: ErrorType.STEPS_EXECUTION_ERROR,
      };
    }
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : String(error),
      errorType: ErrorType.UNKNOWN_ERROR,
    };
  }
}

/**
 * 尝试将 HTML 报告转换为 Maestro YAML
 * 
 * @param reportPath - HTML 报告路径
 * @param testCase - 测试用例
 * @param yamlPath - 目标 YAML 文件路径
 */
export async function tryConvertToMaestroYaml(
  reportPath: string | undefined,
  testCase: TestCase,
  yamlPath: string
): Promise<void> {
  try {
    if (!reportPath) {
      logger.debug('未找到测试报告，跳过 Maestro YAML 转换');
      return;
    }

    logger.info('开始转换 HTML 报告为 Maestro YAML...');

    // 确保输出目录存在
    const outputDir = dirname(yamlPath);
    if (!existsSync(outputDir)) {
      mkdirSync(outputDir, { recursive: true });
    }

    // 转换并保存
    const result = await convertHtmlToYaml(
      reportPath,
      yamlPath,
      {
        appId: testCase.packageName!,
        name: testCase.caseId,
      }
    );

    if (result.success) {
      logger.info(`✓ Maestro YAML 已生成: ${yamlPath}`);
      logger.info(`  命令数量: ${result.commandCount}`);
    } else {
      logger.warn(`Maestro YAML 转换失败: ${result.error}`);
    }
  } catch (error) {
    logger.warn(`转换 Maestro YAML 时出错: ${error}`);
  }
}
