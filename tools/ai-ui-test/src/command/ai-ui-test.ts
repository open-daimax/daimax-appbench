#!/usr/bin/env node

/**
 * UI 自动化测试工具入口
 * 负责参数解析、环境检查和测试路由
 */

import type { TModelConfig } from '@midscene/shared/env';
import { ErrorType, type TestCase, type TestResult, type SuccessResult } from '../types.js';
import { parseCliArguments } from '../helper/cli-parser.js';
import { createModelConfig } from '../helper/config_helper.js';
import { createTestRunDir, type TestRunDir } from '../helper/file_helper.js';
import { 
  checkPlatformEnvironment,
  getFirstAvailableDevice, 
  type DeviceInfo 
} from '../helper/environment_helper.js';
import { logger } from '../helper/logger.js';
import { trackEntry, trackException, trackResult } from '../helper/tracker.js';
import { IOSHelper } from '../helper/ios_helper.js';
import { executeMidsceneTest, executeMidsceneAssertion, startCollectors, stopAndSaveCollectors } from '../midscene/executor.js';
import { 
  checkMaestroYaml, 
  executeMaestroTest,
  tryConvertToMaestroYaml 
} from '../maestro/index.js';
import { readFileSync, unlinkSync } from 'fs';
import { assertLogContains } from '../log/log_collector.js';

// 注册进程退出时的清理函数
process.on('exit', () => {
  IOSHelper.cleanup();
});

process.on('SIGINT', () => {
  IOSHelper.cleanup();
  process.exit(130);
});

process.on('SIGTERM', () => {
  IOSHelper.cleanup();
  process.exit(143);
});

// ============================================================================
// Maestro YAML 解析
// ============================================================================

/**
 * 从 Maestro YAML 文件中解析 appId
 * YAML 格式示例：
 * ```yaml
 * appId: com.autonavi.minimap
 * name: bike-navigation
 * ---
 * - tapOn: ...
 * ```
 */
function parseAppIdFromYaml(yamlPath: string): string | undefined {
  try {
    const content = readFileSync(yamlPath, 'utf-8');
    // 只解析第一个文档（--- 之前的部分）
    const firstDoc = content.split('---')[0];
    // 使用正则提取 appId
    const match = firstDoc.match(/^appId:\s*(.+)$/m);
    if (match) {
      return match[1].trim();
    }
  } catch (error) {
    logger.debug(`解析 YAML appId 失败: ${error}`);
  }
  return undefined;
}

// ============================================================================
// 环境检查
// ============================================================================

/**
 * 检查运行环境
 */
async function checkEnvironment(testCase: TestCase): Promise<DeviceInfo> {
  const { platform, deviceId } = testCase;
  logger.debug('开始环境检查...');

  // 检查平台环境（Android adb、Harmony hdc 等）
  checkPlatformEnvironment(platform);

  // 检测可用设备
  if (platform) {
    logger.debug(`检测 ${platform} 平台的设备...`);
  } else {
    logger.debug('检测可用设备...');
  }
  
  const device = await getFirstAvailableDevice(platform, deviceId);
  
  if (!device) {
    // 根据参数生成更具体的错误信息
    let errorMessage = '未找到可用设备。';
    
    if (deviceId) {
      errorMessage = `未找到设备 ID 为 "${deviceId}" 的设备。`;
    } else if (platform) {
      errorMessage = `未找到 ${platform} 平台的可用设备。`;
    }
    
    errorMessage += '\n请确保设备已连接：\n';
    
    if (!platform || platform === 'android') {
      errorMessage += '- Android: 通过 adb devices 检查\n';
    }
    if (!platform || platform === 'harmony') {
      errorMessage += '- Harmony: 通过 hdc list targets 检查\n';
    }
    if (!platform || platform === 'ios') {
      errorMessage += '- iOS: 确保 WebDriverAgent 运行在尝试链接的地址和端口\n';
    }
    
    throw new Error(errorMessage);
  }

  logger.debug(`找到可用设备: ${device.platform} (${device.deviceId})`);
  return device;
}

// ============================================================================
// 测试执行路由
// ============================================================================

/**
 * 合并 Maestro 结果与 assertion 结果
 */
function mergeAssertionResult(
  maestroResult: SuccessResult,
  assertionResult: TestResult
): TestResult {
  if (assertionResult.success) {
    return {
      success: true,
      reason: assertionResult.reason,
      reportPath: assertionResult.reportPath,
      duration: (maestroResult.duration || 0) + (assertionResult.duration || 0),
      stepsDuration: maestroResult.duration, // Maestro 执行步骤的耗时
      assertionDuration: assertionResult.assertionDuration,
      executionChainGuidance: assertionResult.executionChainGuidance,
      executionChainFilePath: assertionResult.executionChainFilePath,
      // 保留日志和性能数据文件路径（优先使用 assertionResult，回退到 maestroResult）
      logFilePath: assertionResult.logFilePath || maestroResult.logFilePath,
      perfFilePath: assertionResult.perfFilePath || maestroResult.perfFilePath,
      // 保留多维验证结果
      verifications: assertionResult.verifications,
    };
  }

  // assertion 失败
  return {
    success: false,
    error: assertionResult.error,
    errorType: assertionResult.errorType,
    reportPath: assertionResult.reportPath,
    executionChainGuidance: assertionResult.executionChainGuidance,
    executionChainFilePath: assertionResult.executionChainFilePath,
    // 保留日志和性能数据文件路径（优先使用 assertionResult，回退到 maestroResult）
    logFilePath: assertionResult.logFilePath || maestroResult.logFilePath,
    perfFilePath: assertionResult.perfFilePath || maestroResult.perfFilePath,
    // 保留多维验证结果
    verifications: assertionResult.verifications,
  };
}

/**
 * 执行 Maestro 测试并处理断言验证
 * @returns TestResult 如果 Maestro 成功执行，null 如果需要降级到 Midscene
 */
async function executeMaestroWithAssertion(
  yamlPath: string,
  platform: 'android' | 'ios',
  testCase: TestCase,
  deviceInfo: DeviceInfo,
  modelConfig: TModelConfig,
  testRunDir: TestRunDir
): Promise<TestResult | null> {
  logger.info(`检测到 Maestro YAML 文件，使用 Maestro 执行测试`);
  
  // 获取 packageName：优先使用 testCase 中的，否则从 YAML 解析
  const packageName = testCase.packageName || parseAppIdFromYaml(yamlPath) || '';
  if (!packageName) {
    logger.warn('Maestro 测试未找到 packageName，性能采集可能不完整');
  }
  
  // 启动日志和性能采集
  const collectors = await startCollectors(
    platform,
    deviceInfo.deviceId,
    packageName,
    testRunDir
  );
  
  let maestroResult: SuccessResult;
  try {
    const result = await executeMaestroTest(yamlPath, platform);
    
    // Maestro 执行失败，停止采集并返回 null 表示需要降级
    if (!result.success) {
      logger.warn('Maestro 执行失败，降级到 Midscene 继续执行');
      await stopAndSaveCollectors(collectors);
      return null;
    }
    
    maestroResult = result;
  } catch (error) {
    // 发生异常时也停止采集
    await stopAndSaveCollectors(collectors);
    throw error;
  }
  
  // 没有 assertion，停止采集并返回 Maestro 结果
  if (!testCase.assertion || !testCase.assertion.trim()) {
    const collectorResult = await stopAndSaveCollectors(collectors);
    return {
      ...maestroResult,
      logFilePath: collectorResult.logFilePath,
      perfFilePath: collectorResult.perfFilePath,
    };
  }
  
  // 停止采集（assertion 会单独启动它自己的日志采集）
  const collectorResult = await stopAndSaveCollectors(collectors);
  
  // 将 Maestro 采集结果合并到 maestroResult
  const maestroResultWithCollectors: SuccessResult = {
    ...maestroResult,
    logFilePath: collectorResult.logFilePath,
    perfFilePath: collectorResult.perfFilePath,
  };
  
  // 执行 AI 断言验证
  logger.info('执行 AI 断言验证...');
  const assertionResult = await executeMidsceneAssertion(testCase, deviceInfo, modelConfig, testRunDir);
  return mergeAssertionResult(maestroResultWithCollectors, assertionResult);
}

/**
 * 执行日志断言（在测试成功后检查日志内容）
 */
function executeLogAssertion(
  result: TestResult,
  testCase: TestCase
): TestResult {
  // 只在测试成功时执行日志断言
  if (!testCase.logAssert || !result.success) {
    return result;
  }

  const logFilePath = result.logFilePath;
  if (!logFilePath) {
    logger.warn('日志断言已配置但未采集到日志文件');
    return result;
  }

  try {
    const logContent = readFileSync(logFilePath, 'utf-8');
    const logLines = logContent.split('\n');
    const assertResult = assertLogContains(logLines, testCase.logAssert);

    if (!assertResult.passed) {
      // 日志断言失败，将结果改为失败
      return {
        success: false,
        error: `日志断言失败: 在 ${assertResult.totalLines} 行日志中未找到匹配 "${testCase.logAssert}" 的内容`,
        errorType: ErrorType.ASSERTION_FAILED,
        reportPath: result.reportPath,
        logFilePath: result.logFilePath,
        perfFilePath: result.perfFilePath,
        executionChainGuidance: result.executionChainGuidance,
        executionChainFilePath: result.executionChainFilePath,
        verifications: result.verifications,
      };
    }

    logger.debug(`日志断言通过，匹配行: ${assertResult.matchedLine}`);
    return result;
  } catch (e) {
    // 正则表达式错误或文件读取错误
    const errorMessage = e instanceof Error ? e.message : String(e);
    logger.warn(`日志断言执行失败: ${errorMessage}`);
    return {
      success: false,
      error: `日志断言执行失败: ${errorMessage}`,
      errorType: ErrorType.ASSERTION_FAILED,
      reportPath: result.reportPath,
      logFilePath: result.logFilePath,
      perfFilePath: result.perfFilePath,
      executionChainGuidance: result.executionChainGuidance,
      executionChainFilePath: result.executionChainFilePath,
      verifications: result.verifications,
    };
  }
}

/**
 * 执行测试（路由到 Maestro 或 Midscene）
 */
async function executeTest(
  testCase: TestCase,
  deviceInfo: DeviceInfo,
  modelConfig: TModelConfig
): Promise<{ result: TestResult; usedMaestro: boolean }> {
  // 创建测试运行目录
  const testRunDir = createTestRunDir({
    platform: deviceInfo.platform,
    caseId: testCase.caseId,
    deviceId: deviceInfo.deviceId,
  });

  // 只有 Android 和 iOS 平台支持 Maestro
  const isMaestroSupported = 
    (deviceInfo.platform === 'android' || deviceInfo.platform === 'ios') && 
    !!deviceInfo.deviceId;
  
  if (isMaestroSupported) {
    const yamlPath = checkMaestroYaml(testRunDir.maestroYamlPath);
    if (yamlPath) {
      const platform = deviceInfo.platform as 'android' | 'ios';
      let result = await executeMaestroWithAssertion(yamlPath, platform, testCase, deviceInfo, modelConfig, testRunDir);
      if (result) {
        // 执行日志断言（只在测试成功时）
        result = executeLogAssertion(result, testCase);
        return { result, usedMaestro: true };
      }
      // Maestro 失败降级到 Midscene，删除失败的 YAML 以便重新生成
      try {
        unlinkSync(yamlPath);
        logger.info(`已删除失败的 Maestro YAML: ${yamlPath}`);
      } catch {
        // 删除失败不影响主流程
      }
    }
  }
  
  // 使用 Midscene 执行测试
  logger.info('使用 Midscene 执行测试...');
  let result = await executeMidsceneTest(testCase, deviceInfo, modelConfig, testRunDir);

  // 执行日志断言（只在测试成功时）
  result = executeLogAssertion(result, testCase);
  
  // 如果是移动端平台且测试成功，尝试转换为 Maestro YAML
  if (result.success && deviceInfo.platform !== 'web' && testCase.packageName) {
    await tryConvertToMaestroYaml(result.reportPath, testCase, testRunDir.maestroYamlPath);
  }
  
  return { result, usedMaestro: false };
}

// ============================================================================
// 主流程
// ============================================================================

/**
 * 主函数
 */
async function main(): Promise<void> {
  let result: TestResult;
  let deviceInfo: DeviceInfo | undefined;
  let usedMaestro = false;
  
  try {
    // 1. 解析命令行参数
    const testCase = parseCliArguments();

    // 埋点：入口
    trackEntry(testCase);

    // 2. 创建 AI 模型配置（包含认证）
    const modelConfig = await createModelConfig();

    // 3. 如果指定了 URL，自动使用 Web 平台
    if (testCase.url && !testCase.platform) {
      testCase.platform = 'web';
      logger.debug('检测到 URL 参数，自动使用 Web 平台');
    }

    // 4. 打印测试用例信息

    // 5. 环境检查（同时检测设备）
    deviceInfo = await checkEnvironment(testCase);

    // 6. 执行测试
    const executeResult = await executeTest(testCase, deviceInfo, modelConfig);
    result = executeResult.result;
    usedMaestro = executeResult.usedMaestro;
  } catch (error) {
    // 全局错误捕获（主要是环境检查阶段的错误）
    logger.error(`运行出错: ${error}`);
    
    // 埋点：未捕获异常
    trackException(error);
    
    result = {
      success: false,
      error: error instanceof Error ? error.message : String(error),
      errorType: ErrorType.ENVIRONMENT_ERROR,
    };
  }

  // 埋点：根据结果上报 success 或 error
  trackResult(result, deviceInfo?.platform, usedMaestro);

  // 统一输出结果到 stdout
  console.log('UI 测试结果：');
  console.log(JSON.stringify(result));

  // 设置退出码
  process.exit(result.success ? 0 : 1);
}

// 运行主函数
main().catch((error) => {
  logger.error(`程序执行出错: ${error}`);
  process.exit(1);
});
