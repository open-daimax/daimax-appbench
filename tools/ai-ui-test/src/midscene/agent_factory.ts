/**
 * Agent 工厂模块
 * 从 executor.ts 中提取，负责设备连接和 Agent 创建
 */

import { Agent } from '@midscene/core';
import { AndroidAgent, AndroidDevice } from '@midscene/android';
import { HarmonyAgent, HarmonyDevice } from '@midscene/harmony';
import { IOSAgent, IOSDevice } from '@midscene/ios';
import { PlaywrightAgent } from '@midscene/web';
import type { TModelConfig } from '@midscene/shared/env';
import { chromium, type Browser, type Page } from 'playwright';
import fs from 'fs';
import type { TestCase, TestResources, PageDiagnosticsCapture } from '../types.js';
import { logger } from '../helper/logger.js';
import { USE_MIDSCENE_CACHE } from '../helper/constants.js';
import type { DeviceInfo } from '../helper/environment_helper.js';

/**
 * 原子写入页面诊断快照，确保进程被外层超时终止后仍可恢复已采集数据。
 */
function persistPageDiagnostics(capture: PageDiagnosticsCapture): void {
  if (!capture.outputPath) {
    return;
  }
  const tempPath = `${capture.outputPath}.tmp`;
  try {
    fs.writeFileSync(tempPath, JSON.stringify(capture, null, 2), 'utf-8');
    fs.renameSync(tempPath, capture.outputPath);
  } catch (error) {
    logger.warn(`页面诊断快照写入失败: ${error}`);
    try {
      if (fs.existsSync(tempPath)) {
        fs.unlinkSync(tempPath);
      }
    } catch {
      // 忽略临时文件清理错误
    }
  }
}

/**
 * 创建并连接移动设备
 */
export async function createMobileDevice(
  deviceInfo: DeviceInfo
): Promise<AndroidDevice | HarmonyDevice | IOSDevice> {
  switch (deviceInfo.platform) {
    case 'android': {
      logger.debug('连接 Android 设备...');
      const device = new AndroidDevice(deviceInfo.deviceId, {
        scrcpyConfig: {
          enabled: true,
        },
      });
      await device.connect();
      logger.debug('Android 设备连接成功');
      return device;
    }

    case 'harmony': {
      logger.debug('连接 Harmony 设备...');
      const device = new HarmonyDevice(deviceInfo.deviceId);
      await device.connect();
      logger.debug('Harmony 设备连接成功');
      return device;
    }

    case 'ios': {
      logger.debug('连接 iOS 设备...');
      const [wdaHost, wdaPort] = deviceInfo.deviceId.split(':');
      const device = new IOSDevice({
        wdaHost: wdaHost || 'localhost',
        wdaPort: parseInt(wdaPort || '8100', 10),
      });
      await device.connect();
      logger.debug('iOS 设备连接成功');
      return device;
    }

    default:
      throw new Error(`不支持的移动设备平台: ${deviceInfo.platform}`);
  }
}

/**
 * 获取缓存策略配置
 */
function getCacheStrategy(cacheId: string) {
  return USE_MIDSCENE_CACHE
    ? {
        strategy: 'read-only' as const,
        id: cacheId,
      }
    : false;
}

/**
 * 创建 Web 浏览器和页面
 */
export async function createWebBrowser(
  url: string,
  headless: boolean = false,
  viewport?: string,
  pageDiagnostics?: PageDiagnosticsCapture
): Promise<{ browser: Browser; page: Page }> {
  logger.debug(`启动 ${headless ? '无头' : '有头'} 浏览器...`);
  const browser = await chromium.launch({ 
    headless,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--ignore-certificate-errors',
      '--allow-insecure-localhost',
    ],
  });
  logger.debug('浏览器启动成功');
  
  // 解析viewport参数
  let viewportSize: { width: number; height: number } | undefined = undefined;
  if (viewport) {
    const parts = viewport.split('x').map(Number);
    if (parts.length === 2 && parts[0] > 0 && parts[1] > 0) {
      viewportSize = { width: parts[0], height: parts[1] };
      logger.debug(`使用视口尺寸: ${viewport}`);
    }
  }
  
  logger.debug('创建新页面...');
  const page = await browser.newPage(viewportSize ? { viewport: viewportSize } : undefined);
  logger.debug('页面创建成功');

  // 自动 accept 原生浏览器对话框（alert/confirm/prompt/beforeunload）
  // 无头模式下未注册 dialog 处理器时 Playwright 会自动 dismiss，
  // 导致 confirm() 返回 false 中断业务流程、alert/prompt 内容不可见
  page.on('dialog', async (dialog) => {
    logger.info(`原生对话框 [${dialog.type()}] @ ${page.url()}: "${dialog.message()}" -> 自动 accept`);
    await dialog.accept();
  });

  // 注册页面诊断监听：JS 运行时错误、console 错误/警告；按需采集网络请求
  if (pageDiagnostics) {
    if (pageDiagnostics.captureNetwork) {
      page.on('request', (req) => {
        const resourceType = req.resourceType();
        if (resourceType === 'fetch' || resourceType === 'xhr') {
          const postData = req.postData();
          const headers = req.headers();
          pageDiagnostics.networkRequests.push({
            url: req.url(),
            method: req.method(),
            resourceType,
            requestHeaders: headers,
            requestBody: postData ? postData.substring(0, 1000) : undefined,
            startedAt: new Date().toISOString(),
          });
        }
      });

      page.on('response', async (resp) => {
        const respUrl = resp.url();
        const req = resp.request();
        const resType = req.resourceType();
        if (resType === 'fetch' || resType === 'xhr') {
          // 找到对应的请求记录（URL 匹配且尚未填充 status/failed）
          const matched = pageDiagnostics.networkRequests.find(r => r.url === respUrl && r.status === undefined && !r.failed);
          if (matched) {
            const finishedAt = new Date();
            matched.status = resp.status();
            matched.statusText = resp.statusText();
            matched.responseHeaders = resp.headers();
            matched.finishedAt = finishedAt.toISOString();
            if (matched.startedAt) {
              matched.durationMs = finishedAt.getTime() - new Date(matched.startedAt).getTime();
            }
            try {
              const body = await resp.text();
              matched.responseBody = body ? body.substring(0, 2000) : undefined;
            } catch (error) {
              matched.responseBodyError = error instanceof Error ? error.message : String(error);
            }
          }
        }
      });

      page.on('requestfailed', (req) => {
        const resourceType = req.resourceType();
        if (resourceType === 'fetch' || resourceType === 'xhr') {
          const finishedAt = new Date();
          const matched = pageDiagnostics.networkRequests.find(r => r.url === req.url() && r.status === undefined && !r.failed);
          const failureText = req.failure()?.errorText || 'requestfailed';
          if (matched) {
            matched.failed = true;
            matched.failureText = failureText;
            matched.finishedAt = finishedAt.toISOString();
            if (matched.startedAt) {
              matched.durationMs = finishedAt.getTime() - new Date(matched.startedAt).getTime();
            }
          } else {
            const postData = req.postData();
            pageDiagnostics.networkRequests.push({
              url: req.url(),
              method: req.method(),
              resourceType,
              requestHeaders: req.headers(),
              requestBody: postData ? postData.substring(0, 1000) : undefined,
              failed: true,
              failureText,
              startedAt: finishedAt.toISOString(),
              finishedAt: finishedAt.toISOString(),
              durationMs: 0,
            });
          }
        }
      });
    }

    persistPageDiagnostics(pageDiagnostics);

    page.on('pageerror', (error) => {
      pageDiagnostics.jsErrors.push({
        type: 'pageerror',
        name: error.name,
        message: error.message,
        stack: error.stack,
        timestamp: new Date().toISOString(),
        url: page.url(),
      });
      persistPageDiagnostics(pageDiagnostics);
    });

    page.on('console', async (message) => {
      const level = message.type();
      if (level !== 'error' && level !== 'warning') {
        return;
      }
      const args: string[] = [];
      for (const arg of message.args().slice(0, 5)) {
        try {
          const value = await arg.jsonValue();
          args.push(typeof value === 'string' ? value : JSON.stringify(value));
        } catch {
          args.push(String(arg));
        }
      }
      const location = message.location();
      pageDiagnostics.consoleMessages.push({
        level: level === 'warning' ? 'warn' : level,
        message: message.text(),
        timestamp: new Date().toISOString(),
        location: {
          url: location.url,
          lineNumber: location.lineNumber,
          columnNumber: location.columnNumber,
        },
        args,
      });
      persistPageDiagnostics(pageDiagnostics);
    });

    await page.exposeFunction('__evalappRecordUnhandledRejection', (payload: { message: string; name?: string; stack?: string }) => {
      pageDiagnostics.jsErrors.push({
        type: 'unhandledrejection',
        name: payload.name,
        message: payload.message,
        stack: payload.stack,
        timestamp: new Date().toISOString(),
        url: page.url(),
      });
      persistPageDiagnostics(pageDiagnostics);
    });

    await page.addInitScript(`
      window.addEventListener('unhandledrejection', function(event) {
        var reason = event.reason;
        var isError = reason instanceof Error;
        var message = isError ? reason.message : String(reason);
        var name = isError ? reason.name : undefined;
        var stack = isError ? reason.stack : undefined;
        var recorder = window.__evalappRecordUnhandledRejection;
        if (recorder) {
          recorder({ message: message, name: name, stack: stack });
        }
        console.error('[unhandledrejection]', message, stack || '');
      });
    `);

    logger.debug(`已注册页面诊断监听（JS错误、console错误/警告${pageDiagnostics.captureNetwork ? '、网络请求/失败' : ''}）`);
  }

  logger.debug(`导航到 URL: ${url}`);
  await page.goto(url);
  logger.debug('URL 导航成功');

  return { browser, page };
}

/**
 * 创建移动端 Agent
 */
export function createMobileAgent(
  device: AndroidDevice | HarmonyDevice | IOSDevice,
  platform: 'android' | 'harmony' | 'ios',
  cacheId: string,
  modelConfig: TModelConfig,
  onTaskStartTip?: (tip: string) => void | Promise<void>
): Agent {
  const replanLimit = parseInt(process.env.MIDSCENE_REPLANNING_CYCLE_LIMIT || process.env.REPLAN_CYCLE_LIMIT || '10', 10);
  logger.info(`MIDSCENE_REPLANNING_CYCLE_LIMIT from env: ${process.env.MIDSCENE_REPLANNING_CYCLE_LIMIT}, REPLAN_CYCLE_LIMIT: ${process.env.REPLAN_CYCLE_LIMIT}, parsed value: ${replanLimit}`);
  const agentOptions = {
    replanningCycleLimit: replanLimit,
    screenshotShrinkFactor: 2,
    cache: getCacheStrategy(cacheId),
    modelConfig,
    onTaskStartTip,
  };

  switch (platform) {
    case 'android':
      logger.debug('初始化 Android Agent...');
      const androidAgent = new AndroidAgent(device as AndroidDevice, agentOptions);
      logger.debug('Android Agent 初始化成功');
      return androidAgent;

    case 'harmony':
      logger.debug('初始化 Harmony Agent...');
      const harmonyAgent = new HarmonyAgent(device as HarmonyDevice, agentOptions);
      logger.debug('Harmony Agent 初始化成功');
      return harmonyAgent;

    case 'ios':
      logger.debug('初始化 iOS Agent...');
      const iosAgent = new IOSAgent(device as IOSDevice, agentOptions);
      logger.debug('iOS Agent 初始化成功');
      return iosAgent;

    default:
      throw new Error(`不支持的移动设备平台: ${platform}`);
  }
}

type ClickOptions = Parameters<Page['mouse']['click']>[2];

interface ClickPoint {
  x: number;
  y: number;
}

interface CalibratedClickPoint extends ClickPoint {
  adjusted: boolean;
  reason?: string;
  elementSummary?: string;
}

/**
 * 基于 DOM 对视觉点击坐标做校准。
 * 仅使用坐标附近的真实 DOM 结构，不依赖测试文本或业务文案。
 */
async function calibrateClickPoint(page: Page, point: ClickPoint): Promise<CalibratedClickPoint> {
  try {
    return await page.evaluate((rawPoint) => {
      const doc = (globalThis as any).document;
      const win = (globalThis as any).window;
      if (!doc || !win) {
        return { ...rawPoint, adjusted: false, reason: 'document_unavailable' };
      }

      const viewportArea = Math.max(1, win.innerWidth * win.innerHeight);
      const offsets = [
        [0, 0],
        [-6, 0], [6, 0], [0, -6], [0, 6],
        [-12, 0], [12, 0], [0, -12], [0, 12],
        [-12, -12], [12, -12], [-12, 12], [12, 12],
        [-20, 0], [20, 0], [0, -20], [0, 20],
      ];

      const clickableRoles = new Set(['button', 'link', 'menuitem', 'tab', 'checkbox', 'radio', 'switch']);
      const clickableTags = new Set(['BUTTON', 'A', 'INPUT', 'TEXTAREA', 'SELECT', 'OPTION', 'LABEL']);

      function rectOf(el: any) {
        const rect = el?.getBoundingClientRect?.();
        if (!rect || rect.width <= 0 || rect.height <= 0) return null;
        return rect;
      }

      function isVisible(el: any): boolean {
        const rect = rectOf(el);
        if (!rect) return false;
        const style = win.getComputedStyle(el);
        return style.display !== 'none'
          && style.visibility !== 'hidden'
          && Number(style.opacity || '1') > 0.01
          && style.pointerEvents !== 'none';
      }

      function isSemanticClickable(el: any): boolean {
        const tag = String(el.tagName || '').toUpperCase();
        const role = String(el.getAttribute?.('role') || '').toLowerCase();
        const cursor = win.getComputedStyle(el).cursor;
        return clickableTags.has(tag)
          || clickableRoles.has(role)
          || el.hasAttribute?.('onclick')
          || Number(el.getAttribute?.('tabindex')) >= 0
          || cursor === 'pointer';
      }

      function isReasonableClickTarget(el: any): boolean {
        const tag = String(el.tagName || '').toUpperCase();
        if (!el || tag === 'HTML' || tag === 'BODY' || tag === 'CANVAS') return false;
        if (!isVisible(el)) return false;

        const rect = rectOf(el);
        if (!rect) return false;
        const area = rect.width * rect.height;
        if (area < 16 * 16 || area > viewportArea * 0.6) return false;

        const text = String(el.innerText || el.textContent || '').trim();
        return isSemanticClickable(el) || text.length > 0;
      }

      function summarize(el: any): string {
        const tag = String(el.tagName || '').toLowerCase();
        const role = el.getAttribute?.('role');
        const text = String(el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
        return [tag, role ? `role=${role}` : '', text ? `text=${text}` : ''].filter(Boolean).join(' ');
      }

      function collectCandidates(x: number, y: number) {
        const start = doc.elementFromPoint(x, y);
        const result: any[] = [];
        let current = start;
        let depth = 0;
        while (current && depth < 6) {
          if (isReasonableClickTarget(current)) {
            result.push(current);
          }
          current = current.parentElement;
          depth += 1;
        }
        return result;
      }

      let best: any = null;
      let bestScore = Number.POSITIVE_INFINITY;

      for (const [dx, dy] of offsets) {
        const sampleX = rawPoint.x + dx;
        const sampleY = rawPoint.y + dy;
        for (const el of collectCandidates(sampleX, sampleY)) {
          const rect = rectOf(el);
          if (!rect) continue;
          const centerX = rect.left + rect.width / 2;
          const centerY = rect.top + rect.height / 2;
          const distance = Math.hypot(centerX - rawPoint.x, centerY - rawPoint.y);
          const area = rect.width * rect.height;
          const semanticBonus = isSemanticClickable(el) ? -5000 : 0;
          const samplePenalty = Math.hypot(dx, dy) * 10;
          const score = distance * 20 + Math.sqrt(area) + samplePenalty + semanticBonus;
          if (score < bestScore) {
            best = { el, rect, centerX, centerY, distance };
            bestScore = score;
          }
        }
      }

      if (!best) {
        return { ...rawPoint, adjusted: false, reason: 'no_dom_candidate' };
      }

      const maxDistance = Math.max(80, Math.min(180, Math.max(best.rect.width, best.rect.height)));
      if (best.distance > maxDistance) {
        return { ...rawPoint, adjusted: false, reason: 'candidate_too_far', elementSummary: summarize(best.el) };
      }

      return {
        x: best.centerX,
        y: best.centerY,
        adjusted: true,
        reason: 'dom_center',
        elementSummary: summarize(best.el),
      };
    }, point);
  } catch (error) {
    logger.debug(`DOM 点击坐标校准失败，使用原始坐标: ${error}`);
    return { ...point, adjusted: false, reason: 'calibration_error' };
  }
}

/** 包装 Playwright mouse.click，使 Midscene 视觉点击先经过 DOM 中心点校准 */
function installDomClickStabilizer(page: Page): void {
  const mouse = page.mouse as typeof page.mouse & { __domClickStabilized?: boolean };
  if (mouse.__domClickStabilized) {
    return;
  }

  const originalClick = page.mouse.click.bind(page.mouse);
  (page.mouse as any).click = async (x: number, y: number, options?: ClickOptions) => {
    const calibrated = await calibrateClickPoint(page, { x, y });
    if (calibrated.adjusted) {
      logger.debug(
        `DOM 点击校准: (${x.toFixed(1)}, ${y.toFixed(1)}) -> (${calibrated.x.toFixed(1)}, ${calibrated.y.toFixed(1)}) ${calibrated.elementSummary || ''}`
      );
    }
    return originalClick(calibrated.x, calibrated.y, options);
  };
  mouse.__domClickStabilized = true;
  logger.debug('已启用 DOM 点击坐标校准');
}

/**
 * 创建 Web Agent
 */
export function createWebAgent(
  page: Page,
  cacheId: string,
  modelConfig: TModelConfig,
  onTaskStartTip?: (tip: string) => void | Promise<void>
): Agent {
  logger.debug('初始化 Web Agent...');

  const replanLimit = parseInt(process.env.MIDSCENE_REPLANNING_CYCLE_LIMIT || process.env.REPLAN_CYCLE_LIMIT || '10', 10);
  logger.info(`MIDSCENE_REPLANNING_CYCLE_LIMIT from env (Web): ${process.env.MIDSCENE_REPLANNING_CYCLE_LIMIT}, REPLAN_CYCLE_LIMIT: ${process.env.REPLAN_CYCLE_LIMIT}, parsed value: ${replanLimit}`);
  installDomClickStabilizer(page);
  const webAgent = new PlaywrightAgent(page, {
    replanningCycleLimit: replanLimit,
    cache: getCacheStrategy(cacheId),
    modelConfig,
    onTaskStartTip,
  });

  logger.debug('Web Agent 初始化成功');
  return webAgent;
}

/**
 * 打开 scheme/deeplink
 */
export async function openScheme(
  device: AndroidDevice | HarmonyDevice | IOSDevice,
  scheme: string
): Promise<void> {
  logger.debug(`打开 scheme: ${scheme}`);

  try {
    await device.launch(scheme);
    logger.debug('Scheme 打开成功');
    await new Promise(resolve => setTimeout(resolve, 2000));
  } catch (error) {
    logger.warn(`Scheme 打开失败: ${error}`);
  }
}

/**
 * 创建测试 Agent 及其资源清理函数
 */
export async function createTestAgent(
  testCase: TestCase,
  deviceInfo: DeviceInfo,
  modelConfig: TModelConfig,
  onTaskStartTip?: (tip: string) => void | Promise<void>,
  pageDiagnostics?: PageDiagnosticsCapture
): Promise<TestResources> {
  if (deviceInfo.platform === 'web') {
    // Web 平台
    if (!testCase.url) {
      throw new Error('Web 平台测试需要指定 URL 参数（--url）');
    }

    const { browser, page } = await createWebBrowser(
      testCase.url,
      testCase.headless || false,
      testCase.viewport,
      pageDiagnostics
    );
    const agent = createWebAgent(page, testCase.caseId, modelConfig, onTaskStartTip);

    return {
      agent,
      device: undefined,
      browser,
      page,
      entryUrl: testCase.url,
      cleanup: async () => {
        try {
          await browser.close();
          logger.debug('浏览器已关闭');
        } catch (error) {
          logger.warn(`关闭浏览器失败: ${error}`);
        }
      },
    };
  } else {
    // 移动端平台
    const device = await createMobileDevice(deviceInfo);
    const agent = createMobileAgent(device, deviceInfo.platform, testCase.caseId, modelConfig, onTaskStartTip);

    return {
      agent,
      device,
      browser: undefined,
      cleanup: async () => {
        // 显式销毁 iOS device session，避免 WDA 孤儿 session 导致下一次测试 session 冲突
        if (deviceInfo.platform === 'ios') {
          try {
            await (device as IOSDevice).destroy();
            logger.debug('iOS device session 已销毁');
          } catch (error) {
            logger.warn(`销毁 iOS device session 失败: ${error}`);
          }
        }
        logger.debug('移动端资源清理完成');
      },
    };
  }
}

/**
 * 重启应用（移动端）
 */
export async function restartApp(
  device: AndroidDevice | HarmonyDevice | IOSDevice,
  packageName: string,
  platform: 'android' | 'harmony' | 'ios'
): Promise<void> {
  logger.info(`重启应用: ${packageName}`);
  
  try {
    // 关闭应用
    logger.debug('关闭应用...');
    switch (platform) {
      case 'android': {
        const adb = await (device as AndroidDevice).getAdb();
        await adb.shell(`am force-stop ${packageName}`);
        break;
      }
      case 'harmony': {
        const hdc = await (device as HarmonyDevice).getHdc();
        await hdc.forceStop(packageName);
        break;
      }
      case 'ios': {
        const iosDevice = device as IOSDevice;
        await iosDevice.terminate(packageName);
        break;
      }
    }
    logger.debug('应用已关闭');
    
    await new Promise(resolve => setTimeout(resolve, 1000));
    
    // 启动应用
    logger.debug('启动应用...');
    await device.launch(packageName);
    logger.debug('应用启动成功');
    
    await new Promise(resolve => setTimeout(resolve, 2000));
  } catch (error) {
    logger.warn(`应用重启失败: ${error}`);
    throw error;
  }
}
