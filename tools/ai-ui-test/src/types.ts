import { Agent } from '@midscene/core';
import { AndroidDevice } from '@midscene/android';
import { HarmonyDevice } from '@midscene/harmony';
import { IOSDevice } from '@midscene/ios';
import { type Browser, type Page } from 'playwright';

/**
 * 支持的平台类型
 */
export type Platform = 'android' | 'ios' | 'harmony' | 'web' | 'unknown';

/**
 * 需要作为结果返回的错误基类
 * 继承此类的错误会被传播到调用方，而不是被捕获并返回 false
 */
export class ReturnAsResultError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ReturnAsResultError';
  }
}

/**
 * 测试用例
 */
export interface TestCase {
  /** 用例 ID，用于缓存标识 */
  caseId: string;
  /** UI 操作步骤描述（自然语言） */
  steps: string;
  /** 断言验证，用于验证测试结果（自然语言） */
  assertion: string;
  /** 业务知识（可选），在规划阶段传递给模型 */
  knowledge?: string;
  /** 平台类型（可选） */
  platform?: 'android' | 'ios' | 'harmony' | 'web';
  /** 应用名称（可选） */
  appName?: string;
  /** 包名/Bundle ID（可选） */
  packageName?: string;
  /** 设备 ID（可选） */
  deviceId?: string;
  /** 启动 scheme/deeplink（可选），用于启动特定页面或 Activity */
  scheme?: string;
  /** Web URL（可选），用于 Web 平台测试 */
  url?: string;
  /** 是否使用无头模式（可选），仅用于 Web 平台，默认 false */
  headless?: boolean;
  /** 日志断言正则，测试期间设备日志中至少有一行匹配则通过 */
  logAssert?: string;
  /** 视口尺寸，格式: "宽x高" (如 "390x844")，仅Web平台 */
  viewport?: string;
  /** 验证是否使用真实后端（仅Web平台，通过网络请求监听） */
  verifyRealBackend?: boolean;
}

/**
 * 错误类型枚举
 */
export enum ErrorType {
  /** 环境检查错误（设备未找到、adb/hdc 不可用等） */
  ENVIRONMENT_ERROR = 'ENVIRONMENT_ERROR',
  /** UI 操作步骤执行错误 */
  STEPS_EXECUTION_ERROR = 'STEPS_EXECUTION_ERROR',
  /** 断言验证失败 */
  ASSERTION_FAILED = 'ASSERTION_FAILED',
  /** 未知错误 */
  UNKNOWN_ERROR = 'UNKNOWN_ERROR',
}

/** 真实后端验证的请求详情 */
export interface RealBackendRequest {
  url: string;
  method: string;
  /** HTTP 响应状态码 */
  status?: number;
  /** HTTP 响应状态描述 */
  statusText?: string;
  /** 请求头 */
  requestHeaders?: Record<string, string>;
  /** 响应头 */
  responseHeaders?: Record<string, string>;
  /** 请求体 (截断到前1000字符) */
  requestBody?: string;
  /** 响应体 (截断到前2000字符) */
  responseBody?: string;
  /** 响应体读取失败原因 */
  responseBodyError?: string;
  /** Playwright requestfailed 失败原因 */
  failureText?: string;
  /** 是否发生底层网络失败 */
  failed?: boolean;
  /** 请求开始时间（ISO8601） */
  startedAt?: string;
  /** 请求结束时间（ISO8601） */
  finishedAt?: string;
  /** 请求耗时（毫秒） */
  durationMs?: number;
  resourceType: string;
}

/** 页面 JavaScript 运行时错误 */
export interface PageJsError {
  type: 'pageerror' | 'unhandledrejection';
  message: string;
  name?: string;
  stack?: string;
  timestamp: string;
  url?: string;
}

/** 页面 console 错误/警告 */
export interface PageConsoleMessage {
  level: string;
  message: string;
  timestamp: string;
  location?: {
    url?: string;
    lineNumber?: number;
    columnNumber?: number;
  };
  args?: string[];
}

/** 页面诊断原始采集容器 */
export interface PageDiagnosticsCapture {
  networkRequests: RealBackendRequest[];
  jsErrors: PageJsError[];
  consoleMessages: PageConsoleMessage[];
  /** 实时诊断落盘路径，供外层超时后恢复采集结果 */
  outputPath?: string;
  /** 是否采集 fetch/xhr 网络请求；仅需要真实后端验证时开启 */
  captureNetwork?: boolean;
}

/** 页面诊断汇总结果 */
export interface PageDiagnostics {
  pass: boolean;
  method: string;
  reason: string;
  summary: {
    network_monitor_enabled: boolean;
    total_requests: number;
    network_error_count: number;
    http_error_count: number;
    js_error_count: number;
    console_error_count: number;
    console_warn_count: number;
  };
  network_errors: RealBackendRequest[];
  http_errors: RealBackendRequest[];
  js_errors: PageJsError[];
  console_errors: PageConsoleMessage[];
  requests?: RealBackendRequest[];
}

/**
 * 多维验证结果（白屏检测、真实后端验证等）
 */
export interface Verifications {
  white_screen?: {
    detected: boolean;
    reason: string;
  };
  real_backend?: {
    pass: boolean;
    pass_rate?: number;
    method: string;
    reason: string;
    requests?: RealBackendRequest[];
  };
  page_diagnostics?: PageDiagnostics;
}

/**
 * 成功结果接口
 */
export interface SuccessResult {
  /** 执行是否成功 */
  success: true;
  /** 成功依据 */
  reason?: string;
  /** 测试报告文件路径 */
  reportPath?: string;
  /** 执行耗时（毫秒） */
  duration?: number;
  /** UI 操作步骤执行耗时（毫秒） */
  stepsDuration?: number;
  /** 断言验证耗时（毫秒） */
  assertionDuration?: number;
  /** 执行链路引导文案（前馈优化） */
  executionChainGuidance?: string;
  /** 执行链路文件路径 */
  executionChainFilePath?: string;
  /** 设备日志文件路径 */
  logFilePath?: string;
  /** 性能数据文件路径 */
  perfFilePath?: string;
  /** 多维验证结果（白屏检测、真实后端验证等） */
  verifications?: Verifications;
}

/**
 * 失败结果接口
 */
export interface ErrorResult {
  /** 执行是否成功 */
  success: false;
  /** 错误信息 */
  error: string;
  /** 错误类型 */
  errorType: ErrorType;
  /** 失败原因（AI 从报告中提取的观察和分析，比 error 更可读） */
  reason?: string;
  /** 测试报告文件路径（如果生成了报告） */
  reportPath?: string;
  /** 执行链路引导文案（前馈优化） */
  executionChainGuidance?: string;
  /** 执行链路文件路径 */
  executionChainFilePath?: string;
  /** 设备日志文件路径 */
  logFilePath?: string;
  /** 性能数据文件路径 */
  perfFilePath?: string;
  /** 多维验证结果（白屏检测、真实后端验证等） */
  verifications?: Verifications;
}

/**
 * 测试结果类型（成功或失败）
 */
export type TestResult = SuccessResult | ErrorResult;

/**
 * 测试资源，包含 Agent 和清理函数
 */
export interface TestResources {
  /** Agent 实例 */
  agent: Agent; // 使用 any 避免循环依赖，实际类型是 Agent
  /** 设备实例 */
  device?: AndroidDevice | HarmonyDevice | IOSDevice;
  /** 浏览器实例 */
  browser?: Browser;
  /** Web 页面实例 */
  page?: Page;
  /** Web 平台的入口 URL（用于白屏硬重置自愈，回到应用根路径重新进入） */
  entryUrl?: string;
  /** 资源清理函数 */
  cleanup: () => Promise<void>;
}

