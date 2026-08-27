/**
 * 验证器模块
 * 从 executor.ts 中提取，负责后端请求验证逻辑
 */

import type { PageDiagnosticsCapture, RealBackendRequest, Verifications } from '../types.js';

/**
 * 判断一个请求是否为静态资源（应被排除）
 */
function isStaticResource(req: RealBackendRequest): boolean {
  const url = req.url.toLowerCase();

  // 按 resourceType 排除
  const staticResourceTypes = ['stylesheet', 'image', 'font', 'media'];
  if (req.resourceType && staticResourceTypes.includes(req.resourceType.toLowerCase())) {
    return true;
  }

  // 按 URL 扩展名排除
  const staticExtensions = [
    '.js', '.css', '.woff', '.woff2', '.ttf', '.otf',
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp',
    '.mp4', '.mp3', '.wav', '.ogg', '.flac',
    '.eot', '.map',
  ];
  try {
    const pathname = new URL(req.url).pathname.toLowerCase();
    if (staticExtensions.some(ext => pathname.endsWith(ext))) {
      return true;
    }
  } catch {
    if (staticExtensions.some(ext => url.split('?')[0].endsWith(ext))) {
      return true;
    }
  }

  // 按 CDN 域名排除
  const cdnPatterns = [
    'cdn.', '.cdn.', 'unpkg.com', 'cdnjs.', 'jsdelivr.net',
    'fonts.googleapis.com', 'fonts.gstatic.com',
  ];
  if (cdnPatterns.some(pattern => url.includes(pattern))) {
    return true;
  }

  return false;
}

/**
 * 判断一个请求的响应体是否为 HTML 页面（应被排除）
 * HTML 页面响应（如 H5 壳页、登录重定向页）不是真正的后端 API 响应
 */
function isHtmlResponse(req: RealBackendRequest): boolean {
  if (!req.responseBody) return false;
  const trimmed = req.responseBody.trimStart().toLowerCase();
  return trimmed.startsWith('<!doctype') || trimmed.startsWith('<html');
}

/**
 * 剔除浏览器网络层取消产生的重复失败记录。
 * 典型场景：Supabase JS SDK 的 count 查询先发 HEAD 拿 Content-Range 再发 GET 取数据，
 * 浏览器在响应头到达后主动 abort HEAD 连接，导致同一请求被记录两次：
 * 一条 status=200（response 事件）+ 一条 failed/ERR_ABORTED（requestfailed 事件）。
 * 判定条件（三者同时满足才剔除，保证零误报）：
 * 1. 记录为底层失败且无 status（failed=true, status=undefined）
 * 2. failureText 为 ERR_ABORTED（浏览器主动取消，而非后端故障）
 * 3. 同一 method+URL 存在成功记录（status < 400）
 */
export function dedupAbortedDuplicates(requests: RealBackendRequest[]): RealBackendRequest[] {
  const successKeys = new Set(
    requests
      .filter(r => !r.failed && r.status !== undefined && r.status < 400)
      .map(r => `${r.method} ${r.url}`)
  );
  if (successKeys.size === 0) return requests;
  return requests.filter(r => {
    const isAbortedDuplicate = r.failed === true
      && r.status === undefined
      && (r.failureText ?? '').includes('ERR_ABORTED')
      && successKeys.has(`${r.method} ${r.url}`);
    return !isAbortedDuplicate;
  });
}

/**
 * 评估后端请求状态：排除静态资源和 HTML 页面响应后检查真实 API 请求
 */
export function evaluateRealBackend(apiRequests: RealBackendRequest[]): NonNullable<Verifications['real_backend']> {
  // 排除静态资源，保留真实 API 请求
  const realApiRequests = apiRequests.filter(r => !isStaticResource(r));

  // 排除响应体为 HTML 页面的请求（如 H5 壳页、登录重定向页），不算有效 API 请求
  const htmlResponseCount = realApiRequests.filter(r => isHtmlResponse(r)).length;
  const nonHtmlRequests = realApiRequests.filter(r => !isHtmlResponse(r));

  // 剔除浏览器 abort 产生的重复失败记录（如 Supabase HEAD+GET 模式），避免误计后端失败
  const effectiveApiRequests = dedupAbortedDuplicates(nonHtmlRequests);
  const abortedDuplicateCount = nonHtmlRequests.length - effectiveApiRequests.length;

  const failedRequests = effectiveApiRequests.filter(r => r.failed || r.status === undefined || r.status >= 400);
  const hasRequests = effectiveApiRequests.length > 0;

  // 计算请求级别通过率：成功请求数 / 总请求数
  const successCount = effectiveApiRequests.filter(r => !r.failed && r.status !== undefined && r.status < 400).length;
  const pass_rate = hasRequests ? successCount / effectiveApiRequests.length : 0;
  const pass = pass_rate > 0;  // 有成功请求就算pass

  let reason: string;
  if (!hasRequests && apiRequests.length === 0) {
    reason = '未检测到任何 fetch/xhr 请求，可能使用了 mock 数据';
  } else if (!hasRequests && htmlResponseCount > 0) {
    reason = `未检测到任何后端 API 请求（共 ${apiRequests.length} 个 fetch/xhr 请求，排除 ${htmlResponseCount} 个非 API 响应），可能使用了 mock 数据`;
  } else if (!hasRequests) {
    reason = `未检测到任何后端 API 请求（共 ${apiRequests.length} 个 fetch/xhr 请求均为静态资源），可能使用了 mock 数据`;
  } else {
    reason = `检测到 ${effectiveApiRequests.length} 个后端 API 请求，${successCount} 个成功（${(pass_rate * 100).toFixed(1)}%）`;
    if (htmlResponseCount > 0) {
      reason += `，排除了 ${htmlResponseCount} 个非 API 响应`;
    }
    if (abortedDuplicateCount > 0) {
      reason += `，排除了 ${abortedDuplicateCount} 个浏览器取消的重复请求（ERR_ABORTED，同端点已有成功响应）`;
    }
    if (failedRequests.length > 0) {
      const statusList = failedRequests.map(r => {
        try {
          return `${r.method} ${new URL(r.url).pathname} → ${r.failed ? r.failureText : (r.status ?? '无响应')}`;
        } catch {
          return `${r.method} ${r.url.substring(0, 60)} → ${r.failed ? r.failureText : (r.status ?? '无响应')}`;
        }
      }).join('; ');
      reason += `；失败：${statusList}`;
    }
  }

  return {
    pass,
    pass_rate,
    method: 'network_monitor',
    reason,
    requests: simplifyRequests(apiRequests, 20),
  };
}

function simplifyRequests(requests: RealBackendRequest[], limit = 20): RealBackendRequest[] {
  return requests.slice(0, limit).map(r => ({
    url: r.url,
    method: r.method,
    status: r.status,
    statusText: r.statusText,
    failureText: r.failureText,
    failed: r.failed,
    requestHeaders: r.requestHeaders,
    responseHeaders: r.responseHeaders,
    requestBody: r.requestBody,
    responseBody: r.responseBody,
    responseBodyError: r.responseBodyError,
    resourceType: r.resourceType,
    startedAt: r.startedAt,
    finishedAt: r.finishedAt,
    durationMs: r.durationMs,
  }));
}

/**
 * 汇总页面诊断信息：完整记录网络失败、HTTP错误、JS错误与console错误/警告。
 */
export function evaluatePageDiagnostics(capture: PageDiagnosticsCapture): NonNullable<Verifications['page_diagnostics']> {
  const networkMonitorEnabled = capture.captureNetwork === true;
  // 网络错误统计同样剔除浏览器 abort 的重复失败记录，避免误报网络失败
  const dedupedRequests = networkMonitorEnabled ? dedupAbortedDuplicates(capture.networkRequests) : [];
  const networkErrors = networkMonitorEnabled ? dedupedRequests.filter(r => r.failed || r.status === undefined) : [];
  const httpErrors = networkMonitorEnabled ? dedupedRequests.filter(r => !r.failed && r.status !== undefined && r.status >= 400) : [];
  const consoleErrors = capture.consoleMessages.filter(m => m.level === 'error');
  const consoleWarns = capture.consoleMessages.filter(m => m.level === 'warn' || m.level === 'warning');
  const issueCount = networkErrors.length + httpErrors.length + capture.jsErrors.length + consoleErrors.length;

  const reasonParts: string[] = [];
  if (networkErrors.length > 0) reasonParts.push(`网络失败 ${networkErrors.length} 个`);
  if (httpErrors.length > 0) reasonParts.push(`HTTP错误 ${httpErrors.length} 个`);
  if (capture.jsErrors.length > 0) reasonParts.push(`JS运行时错误 ${capture.jsErrors.length} 个`);
  if (consoleErrors.length > 0) reasonParts.push(`console.error ${consoleErrors.length} 条`);
  if (consoleWarns.length > 0) reasonParts.push(`console.warn ${consoleWarns.length} 条`);

  return {
    pass: issueCount === 0,
    method: 'playwright_page_diagnostics',
    reason: reasonParts.length > 0
      ? reasonParts.join('；')
      : networkMonitorEnabled
      ? `未检测到网络失败、HTTP错误、JS运行时错误或console.error（共监听 ${capture.networkRequests.length} 个 fetch/xhr 请求）`
      : '未启用网络请求监听；未检测到JS运行时错误或console.error',
    summary: {
      network_monitor_enabled: networkMonitorEnabled,
      total_requests: capture.networkRequests.length,
      network_error_count: networkErrors.length,
      http_error_count: httpErrors.length,
      js_error_count: capture.jsErrors.length,
      console_error_count: consoleErrors.length,
      console_warn_count: consoleWarns.length,
    },
    network_errors: simplifyRequests(networkErrors, 20),
    http_errors: simplifyRequests(httpErrors, 20),
    js_errors: capture.jsErrors.slice(0, 20),
    console_errors: [...consoleErrors, ...consoleWarns].slice(0, 20),
    requests: simplifyRequests(capture.networkRequests, 50),
  };
}
