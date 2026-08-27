/**
 * Midscene 测试执行器
 * 负责使用 Midscene 执行 UI 自动化测试
 */

import { Agent } from '@midscene/core';
import { AndroidDevice } from '@midscene/android';
import { HarmonyDevice } from '@midscene/harmony';
import { IOSDevice } from '@midscene/ios';
import type { TModelConfig } from '@midscene/shared/env';
import { sleep } from '@midscene/core/utils';
import type { Page } from 'playwright';
import { ErrorType, type TestCase, type TestResult, type Verifications, type PageDiagnosticsCapture } from '../types.js';
import { UI_TEST_TIPS } from '../helper/ui-test-tips.js';
import { extractAssertThought, extractExecutionChain, extractFailureReason, saveExecutionChain } from '../helper/midscene_report_parser.js';
import { logger } from '../helper/logger.js';
import { USE_MIDSCENE_CACHE } from '../helper/constants.js';
import { createTestRunDir, copyReportToRunDir, type TestRunDir } from '../helper/file_helper.js';
import { DeviceLogCollector } from '../log/log_collector.js';
import { DevicePerfCollector } from '../performance/perf_collector.js';
import type { DeviceInfo } from '../helper/environment_helper.js';
import type { Platform } from '../types.js';
import { createTestAgent, openScheme, restartApp } from './agent_factory.js';
import { evaluatePageDiagnostics, evaluateRealBackend } from './verifications.js';

// ============================================================================
// iOS WDA Session 自愈
// ============================================================================

/**
 * 确保 iOS WDA session 仍然有效。
 * 在 executeSteps 完成后、executeAssertion 之前调用。
 * 如果 session 已失效（WDA 返回 404），自动重建连接。
 */
async function ensureIOSSessionAlive(
  device: AndroidDevice | HarmonyDevice | IOSDevice | null,
  platform: Platform,
): Promise<void> {
  if (!device || platform !== 'ios') return;

  const iosDevice = device as IOSDevice;
  try {
    // 探针：尝试获取屏幕尺寸以验证 session 存活
    await iosDevice.size();
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    if (msg.includes('404') || msg.toLowerCase().includes('session')) {
      logger.warn(`iOS WDA session 失效，正在重建: ${msg}`);
      try {
        await iosDevice.connect();
        logger.info('iOS WDA session 重建成功');
      } catch (reconnectError) {
        logger.error(`iOS WDA session 重建失败: ${reconnectError}`);
        throw reconnectError;
      }
    } else {
      throw error;
    }
  }
}

// ============================================================================
// 共享采集逻辑
// ============================================================================

/** 采集器上下文 */
export interface CollectorContext {
  logCollector: DeviceLogCollector;
  perfCollector: DevicePerfCollector | null;
  testRunDir: TestRunDir;
}

/** 采集结果 */
export interface CollectorResult {
  logFilePath?: string;
  perfFilePath?: string;
}

/** 在测试执行前启动日志和性能采集 */
export async function startCollectors(
  platform: Platform,
  deviceId: string,
  packageName: string,
  testRunDir: TestRunDir,
  options?: { skipPerf?: boolean }
): Promise<CollectorContext> {
  const logCollector = new DeviceLogCollector();
  let perfCollector: DevicePerfCollector | null = null;
  
  // 启动日志采集（非阻塞，失败不影响主流程）
  try {
    await logCollector.start(platform, deviceId);
  } catch (e) {
    logger.warn(`日志采集启动失败: ${e}`);
  }
  
  // 启动性能采集（可选，非阻塞）
  if (!options?.skipPerf) {
    perfCollector = new DevicePerfCollector();
    try {
      await perfCollector.start(platform, deviceId, packageName, 2000);
    } catch (e) {
      logger.warn(`性能采集启动失败: ${e}`);
    }
  }
  
  return { logCollector, perfCollector, testRunDir };
}

/** 在测试执行后停止采集并保存文件，返回文件路径 */
export async function stopAndSaveCollectors(
  collectors: CollectorContext | null
): Promise<CollectorResult> {
  // 防御性编程：空值保护，Web 平台等场景可能传入 null
  if (!collectors) {
    return {};
  }
  
  const { testRunDir } = collectors;
  let logFilePath: string | undefined;
  let perfFilePath: string | undefined;
  
  // 停止日志采集并保存
  try {
    await collectors.logCollector.stop();
    const path = collectors.logCollector.saveToFile(testRunDir.logFilePath);
    if (path) logFilePath = path;
  } catch (e) {
    logger.warn(`日志采集停止/保存失败: ${e}`);
  }
  
  // 停止性能采集并保存
  if (collectors.perfCollector) {
    try {
      await collectors.perfCollector.stop();
      const path = collectors.perfCollector.saveToFile(testRunDir.perfFilePath);
      if (path) perfFilePath = path;
    } catch (e) {
      logger.warn(`性能数据保存失败: ${e}`);
    }
  }
  
  return { logFilePath, perfFilePath };
}

/** 执行链路引导文案 */
const EXECUTION_CHAIN_GUIDANCE = '建议查看执行链路文件，分析 AI 的决策过程和操作序列，判断是否需要优化用例（如细化步骤描述、修正操作偏差、增加防御动作等），或将发现的规律沉淀为业务知识以提升后续执行效果。';

/** 白屏检测结果 */
interface WhiteScreenResult {
  detected: boolean;
  reason: string;
}

/**
 * 执行白屏检测（统一抽象，消除重复代码）
 * 
 * @param agent - Midscene Agent 实例
 * @param contextHint - 可选的上下文提示（如"可能是Steps失败原因"）
 * @returns 白屏检测结果
 */
async function detectWhiteScreen(agent: Agent, contextHint?: string): Promise<WhiteScreenResult> {
  let detected = false;
  let reason = '';
  try {
    detected = await agent.aiBoolean(
      '当前页面是否为纯白屏？纯白屏指整个屏幕几乎完全是纯白（或纯色）背景，没有任何可见的文字、图标、图片、按钮或其他UI元素。注意：只要页面存在加载动画、骨架屏、空状态提示、导航栏/Tab栏或任何可见内容（即使内容很少），都不算白屏，应回答否。'
    );
    if (detected) {
      reason = contextHint
        ? `AI视觉判断：页面为纯白屏，无任何可见内容（${contextHint}）`
        : 'AI视觉判断：页面为纯白屏，无任何可见内容';
    } else {
      reason = 'AI视觉判断：页面包含正常内容';
    }
  } catch (e) {
    reason = `白屏检测异常: ${e instanceof Error ? e.message : String(e)}`;
  }
  return { detected, reason };
}

/**
 * 构建 AI 上下文信息
 */
function buildAIContext(testCase: TestCase, options?: { hasBrowserNavigation?: boolean }): string {
  const parts: string[] = [];
  
  // 添加 UI 测试操作技巧提示词
  parts.push(UI_TEST_TIPS);
  
  // 添加应用信息
  if (testCase.appName || testCase.packageName) {
    let appInfo = '## 应用信息\n\n';
    if (testCase.appName) {
      appInfo += `应用名称：${testCase.appName}\n`;
    }
    if (testCase.packageName) {
      appInfo += `包名：${testCase.packageName}`;
    }
    parts.push(appInfo);
  }
  
  // 添加命令行传入的业务知识
  if (testCase.knowledge) {
    parts.push(`## 业务知识\n\n${testCase.knowledge}`);
  }
  
  // 浏览器页面导航能力提示：这是评测执行器能力，不绑定具体业务平台或页面。
  if (options?.hasBrowserNavigation) {
    parts.push(
      '## 浏览器页面导航能力\n\n'
      + '当前评测对象运行在浏览器页面中。页面内没有可见返回按钮、非 tab 页面看不到底部导航、或需要回到上一级时，浏览器历史返回是一种可用的用户操作方式。请优先按测试目标灵活选择可达路径，不要把“页面必须存在内置返回按钮”作为通过条件。\n\n'
      + '注意：底部 Tab 之间的切换通常不会被记录进浏览器历史栈（就像原生小程序 Tab 切换一样不可“返回撤销”）。如果你点击了某个 Tab 或按钮后发现不是想要的页面，优先直接点击正确的目标 Tab/按钮去纠正，而不要用浏览器返回（GoBack）去“撤销”一次 Tab 切换——对 Tab 切换执行返回可能会跳出应用的正常页面栈，导致页面持续空白且刷新也无法恢复。返回操作更适合用于撤销“进入详情页”这类会产生新页面的跳转。'
    );
  }

  return parts.filter(Boolean).join('\n\n');
}

/** steps 执行上下文 */
interface StepExecutionOptions {
  page?: Page;
  /** Web 平台入口 URL，用于硬重置自愈 */
  entryUrl?: string;
}

/** 等待 Web 页面在 history 返回或 SPA 路由变化后稳定 */
async function waitForWebPageStable(page: Page): Promise<void> {
  try {
    await page.waitForLoadState('domcontentloaded', { timeout: 3000 });
  } catch {
    // SPA 路由不一定触发完整 load，忽略超时并用短等待兜底。
  }
  await page.waitForTimeout(800);
}

/** Web/H5 通用浏览器历史返回能力，不绑定具体页面或业务语义 */
async function performWebHistoryBack(page: Page): Promise<boolean> {
  const historyLength = Number(await page.evaluate('window.history.length').catch(() => 0));
  if (historyLength <= 1) {
    logger.debug('semanticBack: history 栈不足，跳过浏览器返回');
    return false;
  }

  const beforeUrl = page.url();
  try {
    await page.goBack({ waitUntil: 'domcontentloaded', timeout: 5000 });
    await waitForWebPageStable(page);
    logger.info(`semanticBack: 已执行 page.goBack (${beforeUrl} -> ${page.url()})`);
    return true;
  } catch (error) {
    logger.warn(`semanticBack: page.goBack 失败，尝试 window.history.back(): ${error}`);
  }

  try {
    await page.evaluate('window.history.back()');
    await waitForWebPageStable(page);
    logger.info(`semanticBack: 已执行 window.history.back (${beforeUrl} -> ${page.url()})`);
    return page.url() !== beforeUrl;
  } catch (error) {
    logger.warn(`semanticBack: window.history.back 失败: ${error}`);
    return false;
  }
}

/** Web/H5 执行失败后尝试浏览器历史返回，再重试原始步骤 */
async function recoverWebNavigationAndRetry(agent: Agent, steps: string, options: StepExecutionOptions): Promise<boolean> {
  if (!options.page) {
    return false;
  }

  const recovered = await performWebHistoryBack(options.page);
  if (!recovered) {
    return false;
  }

  logger.info('semanticBack: 浏览器返回后重试原始 UI 操作步骤');
  await agent.aiAct(steps);
  return true;
}

/**
 * 硬重置自愈：当“浏览器历史返回 + 重试”仍无法恢复时（例如 Tab 切换未入栈导致 GoBack 跳出应用路由体系），
 * 直接导航回 Web 入口 URL 重新进入应用根路径，再重试一次原始步骤。
 * 与轻量的 performWebHistoryBack 不同，这里直接放弃当前可能已“跳出路由体系”的历史状态，以入口 URL 作为已知可靠的回退点。
 */
async function recoverWhiteScreenByHardReset(agent: Agent, steps: string, options: StepExecutionOptions): Promise<boolean> {
  if (!options.page || !options.entryUrl) {
    return false;
  }

  try {
    logger.warn(`whiteScreenRecovery: 尝试硬重置，导航回入口 URL: ${options.entryUrl}`);
    await options.page.goto(options.entryUrl, { waitUntil: 'domcontentloaded', timeout: 8000 });
    await waitForWebPageStable(options.page);
  } catch (error) {
    logger.warn(`whiteScreenRecovery: 导航回入口 URL 失败: ${error}`);
    return false;
  }

  logger.info('whiteScreenRecovery: 硬重置完成，重试原始 UI 操作步骤');
  await agent.aiAct(steps);
  return true;
}

/**
 * 尝试依次执行“浏览器历史返回重试”与“硬重置自愈重试”，任一成功则认为恢复成功。
 */
async function tryRecoverAndRetry(agent: Agent, steps: string, options: StepExecutionOptions): Promise<boolean> {
  try {
    if (await recoverWebNavigationAndRetry(agent, steps, options)) {
      return true;
    }
  } catch (retryError) {
    logger.warn(`浏览器返回重试失败: ${retryError}`);
  }

  try {
    if (await recoverWhiteScreenByHardReset(agent, steps, options)) {
      return true;
    }
  } catch (hardResetError) {
    logger.warn(`硬重置自愈失败: ${hardResetError}`);
  }

  return false;
}

/**
 * 执行 UI 操作步骤
 */
async function executeSteps(agent: Agent, steps: string, options: StepExecutionOptions): Promise<void> {
  try {
    await agent.aiAct(steps);
  } catch (error) {
    logger.warn(`UI 操作步骤执行失败，尝试 Web/H5 恢复: ${error}`);
    const recovered = await tryRecoverAndRetry(agent, steps, options);
    if (!recovered) {
      throw error;
    }
    logger.debug('UI 操作步骤执行完成（恢复后）');
    return;
  }

  logger.debug(`UI 操作步骤执行完成`);
}

/**
 * 执行断言验证
 */
async function executeAssertion(agent: Agent, assertion: string): Promise<void> {
  await agent.aiAssert(assertion);
  logger.debug(`断言验证通过`);
}

/**
 * 生成测试报告并提取成功依据
 */
async function generateReport(agent: Agent): Promise<{ reportPath: string; reason?: string }> {
  logger.debug('生成测试报告...');
  agent.writeOutActionDumps();

  const reportPath = agent.reportFile || '';
  if (reportPath) {
    logger.info(`测试报告: ${reportPath}`);
  }

  const reason = await extractAssertThought(reportPath);
  return { reportPath, reason };
}

/**
 * 尝试生成测试报告（即使测试失败）
 */
function tryGenerateReport(agent: Agent | null): string | undefined {
  if (!agent) {
    return undefined;
  }
  
  try {
    agent.writeOutActionDumps();
    const reportPath = agent.reportFile || '';
    if (reportPath) {
      logger.debug(`部分测试报告已生成: ${reportPath}`);
      return reportPath;
    }
  } catch (error) {
    logger.debug(`生成测试报告失败: ${error}`);
  }
  
  return undefined;
}

/**
 * 构建错误结果
 */
async function buildErrorResult(
  error: unknown,
  errorType: ErrorType,
  agent: Agent | null,
  testRunDir?: TestRunDir,
  logFilePath?: string,
  perfFilePath?: string,
  verifications?: Verifications
): Promise<TestResult> {
  const reportPath = tryGenerateReport(agent);
  const errorMessage = error instanceof Error ? error.message : String(error);
  
  const errorPrefix = errorType === ErrorType.STEPS_EXECUTION_ERROR 
    ? 'UI 操作步骤执行失败' 
    : errorType === ErrorType.ASSERTION_FAILED
    ? '断言验证失败'
    : '测试执行失败';

  // 尝试提取执行链路
  let chainResult: { guidance: string; filePath: string } | null = null;
  if (reportPath && testRunDir) {
    chainResult = await tryExtractAndSaveChain(reportPath, testRunDir.executionChainPath);
  }

  // 尝试从报告中提取 AI 观察到的失败原因
  let reason: string | undefined;
  if (reportPath) {
    try {
      reason = await extractFailureReason(reportPath);
      if (reason) {
        logger.debug(`提取到失败原因: ${reason.substring(0, 100)}...`);
      }
    } catch (e) {
      logger.debug(`提取失败原因失败: ${e}`);
    }
  }

  return {
    success: false,
    error: `${errorPrefix}: ${errorMessage}`,
    errorType,
    reason,
    reportPath,
    logFilePath,
    perfFilePath,
    ...(verifications && { verifications }),
    ...(chainResult && {
      executionChainGuidance: chainResult.guidance,
      executionChainFilePath: chainResult.filePath,
    }),
  };
}

/**
 * 尝试提取并保存执行链路
 */
async function tryExtractAndSaveChain(
  reportPath: string | undefined,
  executionChainPath: string
): Promise<{ guidance: string; filePath: string } | null> {
  if (!reportPath) {
    return null;
  }
  
  try {
    const chain = await extractExecutionChain(reportPath);
    if (!chain) {
      return null;
    }
    
    const filePath = saveExecutionChain(chain, executionChainPath);
    return { guidance: EXECUTION_CHAIN_GUIDANCE, filePath };
  } catch (error) {
    logger.debug(`提取执行链路失败: ${error}`);
    return null;
  }
}

function buildWebVerifications(
  base: Verifications,
  pageDiagnostics: PageDiagnosticsCapture | undefined,
  shouldVerifyRealBackend: boolean,
): Verifications {
  if (!pageDiagnostics) {
    return base;
  }
  base.page_diagnostics = evaluatePageDiagnostics(pageDiagnostics);
  if (shouldVerifyRealBackend) {
    base.real_backend = evaluateRealBackend(pageDiagnostics.networkRequests);
  }
  return base;
}

/**
 * 使用 Midscene 执行测试
 */
export async function executeMidsceneTest(
  testCase: TestCase,
  deviceInfo: DeviceInfo,
  modelConfig: TModelConfig,
  testRunDir?: TestRunDir,  // 新增：外部传入则复用
): Promise<TestResult> {
  const startTime = Date.now();
  let stepsStartTime = 0;
  let assertionStartTime = 0;
  let agent: Agent | null = null;
  let device: AndroidDevice | HarmonyDevice | IOSDevice | null = null;
  let cleanup: (() => Promise<void>) | null = null;
  let collectors: CollectorContext | null = null;

  // 页面诊断采集：Web/H5 全量开启 JS 错误监控；仅真实后端验证场景采集 fetch/xhr 网络请求
  const pageDiagnostics: PageDiagnosticsCapture | undefined = deviceInfo.platform === 'web'
    ? { networkRequests: [], jsErrors: [], consoleMessages: [], captureNetwork: !!testCase.verifyRealBackend }
    : undefined;

  // 复用或创建测试运行目录
  const runDir = testRunDir ?? createTestRunDir({
    platform: deviceInfo.platform,
    caseId: testCase.caseId,
    deviceId: deviceInfo.deviceId,
  });
  if (pageDiagnostics) {
    pageDiagnostics.outputPath = runDir.pageDiagnosticsPath;
  }

  try {
    // 创建 Agent 和清理函数
    const resources = await createTestAgent(testCase, deviceInfo, modelConfig, (tip) => {
      logger.info(`[Running] ${tip}`);
    }, pageDiagnostics);
    agent = resources.agent;
    device = resources.device || null;
    cleanup = resources.cleanup;
    let appRestarted = false;

    // 如果是移动端且提供了包名，先重启应用
    if (deviceInfo.platform !== 'web' && device && testCase.packageName) {
      await restartApp(device, testCase.packageName, deviceInfo.platform);
      appRestarted = true;
    }
    
    // 如果指定了 scheme，先打开
    if (device && testCase.scheme) {
      if (appRestarted) {
        await sleep(3000);
      }
      await openScheme(device, testCase.scheme);
    }

    // 启动日志和性能采集
    collectors = await startCollectors(
      deviceInfo.platform,
      deviceInfo.deviceId,
      testCase.packageName || '',
      runDir
    );

    logger.debug(`操作步骤: ${testCase.steps}`);
    logger.debug(`断言验证: ${testCase.assertion}`);

    // 构建 AI 上下文
    const context = buildAIContext(testCase, { hasBrowserNavigation: !!resources.page });
    if (context) {
      logger.debug(`AI 上下文已构建 (${context.length} 字符)`);
      agent.setAIActContext(context);
    }

    // 执行 UI 操作步骤
    stepsStartTime = Date.now();
    try {
      await executeSteps(agent, testCase.steps, {
        page: resources.page,
        entryUrl: resources.entryUrl,
      });
    } catch (error) {
      logger.error(`UI 操作步骤执行失败: ${error}`);
      // Steps 失败时仍执行白屏检测（白屏可能是操作失败的根本原因）
      const wsResult = await detectWhiteScreen(agent, '可能是Steps失败原因');
      const stepsVerifications = buildWebVerifications({
        white_screen: { detected: wsResult.detected, reason: wsResult.reason },
      }, pageDiagnostics, !!testCase.verifyRealBackend && deviceInfo.platform === 'web');
      const collectorResult = await stopAndSaveCollectors(collectors);
      return await buildErrorResult(error, ErrorType.STEPS_EXECUTION_ERROR, agent, runDir, collectorResult.logFilePath, collectorResult.perfFilePath, stepsVerifications);
    }

    // 执行断言验证
    await sleep(2000);

    // iOS WDA session 自愈：steps 执行耗时较长后 session 可能已失效
    await ensureIOSSessionAlive(device, deviceInfo.platform);

    assertionStartTime = Date.now();
    let assertionFailed = false;
    let assertionError: unknown;

    try {
      await executeAssertion(agent, testCase.assertion);
    } catch (error) {
      logger.error(`断言验证失败: ${error}`);
      assertionFailed = true;
      assertionError = error;
    }

    logger.info('测试执行完成');

    // 写入缓存（仅在启用缓存时执行）
    if (USE_MIDSCENE_CACHE) {
      try {
        logger.debug('写入缓存...');
        await agent.flushCache();
        logger.debug('缓存写入成功');
      } catch (error) {
        logger.warn(`缓存写入失败: ${error}`);
      }
    }

    // 白屏检测（所有用例、所有平台）
    const wsResult = await detectWhiteScreen(agent);

    // 组装 verifications
    const verifications = buildWebVerifications({
      white_screen: {
        detected: wsResult.detected,
        reason: wsResult.reason,
      },
    }, pageDiagnostics, !!testCase.verifyRealBackend && deviceInfo.platform === 'web');

    // 停止采集并获取文件路径（在返回之前）
    const collectorResult = await stopAndSaveCollectors(collectors);
    collectors = null; // 标记已处理，避免 finally 中重复处理

    // 如果断言失败，返回失败结果
    if (assertionFailed) {
      return await buildErrorResult(assertionError, ErrorType.ASSERTION_FAILED, agent, runDir, collectorResult.logFilePath, collectorResult.perfFilePath, verifications);
    }

    // 生成测试报告并提取成功依据
    const { reportPath: midsceneReportPath, reason } = await generateReport(agent);

    // 复制报告到统一目录
    const reportPath = copyReportToRunDir(midsceneReportPath, runDir.reportPath);

    // 提取执行链路
    const chainResult = await tryExtractAndSaveChain(midsceneReportPath, runDir.executionChainPath);

    // 计算耗时
    const duration = Date.now() - startTime;
    const stepsDuration = assertionStartTime - stepsStartTime;
    const assertionDuration = Date.now() - assertionStartTime;

    // 返回成功结果
    return {
      success: true,
      reason,
      reportPath,
      duration,
      stepsDuration,
      assertionDuration,
      logFilePath: collectorResult.logFilePath,
      perfFilePath: collectorResult.perfFilePath,
      verifications,
      ...(chainResult && {
        executionChainGuidance: chainResult.guidance,
        executionChainFilePath: chainResult.filePath,
      }),
    };
  } catch (error) {
    logger.error(`测试执行失败: ${error}`);
    // 确保停止采集
    let collectorResult: CollectorResult = {};
    if (collectors) {
      collectorResult = await stopAndSaveCollectors(collectors);
    }
    // 尝试执行白屏检测（如果 agent 可用）
    let catchVerifications: Verifications | undefined;
    if (agent) {
      const wsResult = await detectWhiteScreen(agent);
      catchVerifications = buildWebVerifications({
        white_screen: {
          detected: wsResult.detected,
          reason: wsResult.reason,
        },
      }, pageDiagnostics, !!testCase.verifyRealBackend && deviceInfo.platform === 'web');
    }
    return await buildErrorResult(error, ErrorType.UNKNOWN_ERROR, agent, runDir, collectorResult.logFilePath, collectorResult.perfFilePath, catchVerifications);
  } finally {
    // 清理资源
    if (cleanup) {
      await cleanup();
    }
  }
}

/**
 * 单独执行 AI 断言验证
 * 用于在 Maestro 测试成功后，补充 AI assertion 过程
 * 注意：仅采集日志，不采集性能数据
 */
export async function executeMidsceneAssertion(
  testCase: TestCase,
  deviceInfo: DeviceInfo,
  modelConfig: TModelConfig,
  testRunDir?: TestRunDir,  // 新增：外部传入则复用
): Promise<TestResult> {
  const startTime = Date.now();
  let assertionStartTime = 0;
  let agent: Agent | null = null;
  let cleanup: (() => Promise<void>) | null = null;
  let collectors: CollectorContext | null = null;

  // 页面诊断采集：Web/H5 全量开启 JS 错误监控；仅真实后端验证场景采集 fetch/xhr 网络请求
  const pageDiagnostics: PageDiagnosticsCapture | undefined = deviceInfo.platform === 'web'
    ? { networkRequests: [], jsErrors: [], consoleMessages: [], captureNetwork: !!testCase.verifyRealBackend }
    : undefined;

  // 验证 assertion 参数
  if (!testCase.assertion) {
    return {
      success: false,
      error: '未提供断言验证内容',
      errorType: ErrorType.ASSERTION_FAILED,
    };
  }

  // 复用或创建测试运行目录
  const runDir = testRunDir ?? createTestRunDir({
    platform: deviceInfo.platform,
    caseId: testCase.caseId,
    deviceId: deviceInfo.deviceId,
  });
  if (pageDiagnostics) {
    pageDiagnostics.outputPath = runDir.pageDiagnosticsPath;
  }

  try {
    // 创建 Agent 和清理函数
    logger.debug('创建 Agent 用于断言验证...');
    const resources = await createTestAgent(testCase, deviceInfo, modelConfig, (tip) => {
      logger.info(`[Running] ${tip}`);
    }, pageDiagnostics);
    agent = resources.agent;
    cleanup = resources.cleanup;

    // 启动日志采集（跳过性能采集，因为 assertion 不需要）
    collectors = await startCollectors(
      deviceInfo.platform,
      deviceInfo.deviceId,
      testCase.packageName || '',
      runDir,
      { skipPerf: true }
    );

    // 构建 AI 上下文（与 executeMidsceneTest 保持一致）
    const context = buildAIContext(testCase, { hasBrowserNavigation: !!resources.page });
    if (context) {
      logger.debug(`AI 上下文已构建 (${context.length} 字符)`);
      agent.setAIActContext(context);
    }

    logger.debug(`断言验证: ${testCase.assertion}`);

    // 等待 UI 稳定
    await sleep(2000);

    // 执行断言验证
    assertionStartTime = Date.now();
    let assertionFailed = false;
    let assertionError: unknown;

    try {
      await executeAssertion(agent, testCase.assertion);
    } catch (error) {
      logger.error(`断言验证失败: ${error}`);
      assertionFailed = true;
      assertionError = error;
    }

    logger.info('断言验证执行完成');

    // 白屏检测（所有用例、所有平台）
    const wsResult = await detectWhiteScreen(agent);

    // 组装 verifications
    const verifications = buildWebVerifications({
      white_screen: {
        detected: wsResult.detected,
        reason: wsResult.reason,
      },
    }, pageDiagnostics, !!testCase.verifyRealBackend && deviceInfo.platform === 'web');

    // 写入缓存（仅在启用缓存时执行）
    if (USE_MIDSCENE_CACHE) {
      try {
        logger.debug('写入缓存...');
        await agent.flushCache();
        logger.debug('缓存写入成功');
      } catch (error) {
        logger.warn(`缓存写入失败: ${error}`);
      }
    }

    // 停止采集并获取文件路径（在返回之前）
    const collectorResult = await stopAndSaveCollectors(collectors);
    collectors = null; // 标记已处理

    // 如果断言失败，返回失败结果
    if (assertionFailed) {
      return await buildErrorResult(assertionError, ErrorType.ASSERTION_FAILED, agent, runDir, collectorResult.logFilePath, undefined, verifications);
    }

    // 生成测试报告并提取成功依据
    const { reportPath: midsceneReportPath, reason } = await generateReport(agent);

    // 复制报告到统一目录
    const reportPath = copyReportToRunDir(midsceneReportPath, runDir.reportPath);

    // 提取执行链路
    const chainResult = await tryExtractAndSaveChain(midsceneReportPath, runDir.executionChainPath);

    // 计算耗时
    const assertionDuration = Date.now() - assertionStartTime;
    const duration = Date.now() - startTime;

    // 返回成功结果（不包含 perfFilePath）
    return {
      success: true,
      reason,
      reportPath,
      duration,
      assertionDuration,
      logFilePath: collectorResult.logFilePath,
      verifications,
      ...(chainResult && {
        executionChainGuidance: chainResult.guidance,
        executionChainFilePath: chainResult.filePath,
      }),
    };
  } catch (error) {
    logger.error(`断言验证执行失败: ${error}`);
    // 确保停止采集
    let collectorResult: CollectorResult = {};
    if (collectors) {
      collectorResult = await stopAndSaveCollectors(collectors);
    }
    // 尝试执行白屏检测（如果 agent 可用）
    let catchVerifications: Verifications | undefined;
    if (agent) {
      const wsResult = await detectWhiteScreen(agent);
      catchVerifications = buildWebVerifications({
        white_screen: {
          detected: wsResult.detected,
          reason: wsResult.reason,
        },
      }, pageDiagnostics, !!testCase.verifyRealBackend && deviceInfo.platform === 'web');
    }
    return await buildErrorResult(error, ErrorType.UNKNOWN_ERROR, agent, runDir, collectorResult.logFilePath, undefined, catchVerifications);
  } finally {
    // 清理资源
    if (cleanup) {
      await cleanup();
    }
  }
}

/**
 * 获取 Agent 的报告文件路径（用于 YAML 转换）
 */
export function getAgentReportPath(agent: Agent): string | undefined {
  return agent.reportFile || undefined;
}
