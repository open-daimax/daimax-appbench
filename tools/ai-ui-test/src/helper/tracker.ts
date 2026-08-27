/**
 * 埋点工具模块
 * 用于发送技能使用统计数据
 */

import { execSync, spawn } from 'child_process';
import os from 'os';

// 技能名称常量
const SKILL_NAME = 'ai-ui-test';

// 埋点上报地址：仅在显式设置环境变量 AI_UI_TEST_TRACK_URL 时启用，默认不发送任何数据
const TRACK_URL = process.env.AI_UI_TEST_TRACK_URL || '';

/**
 * 获取 device_id：优先使用 Git 用户邮箱，失败则降级到系统用户名
 */
function getDeviceId(): string | undefined {
  try {
    const email = execSync('git config user.email', {
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'ignore']
    }).trim();
    if (email) return email;
  } catch {
    // git email 获取失败，降级处理
  }

  try {
    const username = os.userInfo().username;
    if (username) return username;
  } catch {
    // 系统用户名获取失败
  }

  return undefined;
}

/**
 * 埋点请求体结构
 */
interface TrackerBody {
  eventId: string;
  c1: string;
  ext: Record<string, unknown>;
  device_id?: string;
}

/**
 * 发送埋点数据（使用 curl 命令，完全不阻塞）
 * @param params 额外的埋点参数（可选）
 */
export function sendTracker(params?: Record<string, unknown>): void {
  try {
    // 未配置上报地址时静默跳过（开源默认行为）
    if (!TRACK_URL) return;

    // 获取 device_id
    const deviceId = getDeviceId();

    // 构造请求体
    const body: TrackerBody = {
      eventId: 'skillTools',
      c1: SKILL_NAME,
      ext: {
        skill_name: SKILL_NAME,
        ...(params || {})
      }
    };

    // 如果获取到 device_id，则添加到请求体
    if (deviceId) {
      body.device_id = deviceId;
    }

    // 使用 curl 发送请求（跨平台，最可靠）
    const jsonBody = JSON.stringify(body);
    const curlArgs = [
      '-X', 'POST',
      '-H', 'Content-Type: application/json',
      '-d', jsonBody,
      '--max-time', '3',  // 3秒超时
      '--silent',         // 静默模式
      TRACK_URL
    ];

    // 启动独立进程发送埋点
    const child = spawn('curl', curlArgs, {
      detached: true,    // 独立进程，不受主进程影响
      stdio: 'ignore'    // 忽略输入输出
    });

    child.on('error', () => {});

    // 允许主进程退出而不等待子进程
    child.unref();
  } catch {
    // 静默处理错误：不影响主流程
  }
}

/**
 * 上报入口埋点
 */
export function trackEntry(testCase: { platform?: string; packageName?: string; url?: string; assertion?: string; knowledge?: string }): void {
  sendTracker({
    action: 'entry',
    platform: testCase.platform || 'auto',
    has_package: !!testCase.packageName,
    has_url: !!testCase.url,
    has_assertion: !!testCase.assertion,
    has_knowledge: !!testCase.knowledge,
  });
}

/**
 * 上报未捕获异常
 */
export function trackException(error: unknown): void {
  sendTracker({
    action: 'error',
    error_type: 'unexpected_exception',
    error_message: error instanceof Error ? error.message?.substring(0, 200) : String(error).substring(0, 200),
  });
}

/**
 * 上报测试结果（自动区分 success / fail / error）
 */
export function trackResult(
  result: { success: boolean; duration?: number; stepsDuration?: number; assertionDuration?: number; error?: string; errorType?: string },
  platform: string | undefined,
  usedMaestro: boolean
): void {
  const strategy = usedMaestro ? 'maestro' : 'midscene';

  if (result.success) {
    sendTracker({
      action: 'success',
      platform: platform || 'unknown',
      strategy,
      duration: result.duration,
      steps_duration: result.stepsDuration,
      assertion_duration: result.assertionDuration,
    });
  } else {
    sendTracker({
      action: result.errorType === 'ASSERTION_FAILED' ? 'fail' : 'error',
      platform: platform || 'unknown',
      strategy,
      error_type: result.errorType,
      error_message: result.error?.substring(0, 200),
    });
  }
}
