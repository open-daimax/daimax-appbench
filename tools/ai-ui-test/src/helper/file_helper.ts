/**
 * 统一管理测试产物输出目录
 * 
 * 目录结构：.test_intermediates/ai-ui-test/{platform}_{caseId}_{deviceId}_{timestamp}/
 * 
 * 该目录下存放：
 * - device.log          设备日志
 * - performance.json    性能采集数据
 * - page_diagnostics.json 页面诊断实时快照
 * - report.html         Midscene 测试报告（从 Midscene 输出目录复制）
 * - execution_chain.md  执行链路 Markdown
 * - maestro.yaml        Maestro 测试用例
 */

import path from 'path';
import fs from 'fs';

// 基础常量
const TEST_INTERMEDIATES_BASE = '.test_intermediates';
const AI_UI_TEST_DIR = 'ai-ui-test';

/**
 * TestRunDir 表示一次测试运行的输出目录上下文
 */
export interface TestRunDir {
  /** 运行目录的绝对路径 */
  dirPath: string;
  /** 设备日志文件路径 */
  logFilePath: string;
  /** 性能数据文件路径 */
  perfFilePath: string;
  /** 执行链路 Markdown 文件路径 */
  executionChainPath: string;
  /** Maestro YAML 文件路径 */
  maestroYamlPath: string;
  /** 页面诊断实时快照文件路径 */
  pageDiagnosticsPath: string;
  /** 报告文件路径（从 Midscene 复制后的路径） */
  reportPath: string;
}

/**
 * 净化字符串，只保留安全字符
 */
function sanitize(str: string): string {
  return str.replace(/[^a-zA-Z0-9_-]/g, '_');
}

/**
 * 创建一次测试运行的输出目录，返回所有文件路径
 */
export function createTestRunDir(options: {
  platform: string;
  caseId: string;
  deviceId: string;
}): TestRunDir {
  const { platform, caseId, deviceId } = options;
  
  // 生成时间戳（包含毫秒，避免并发场景目录冲突）
  const now = new Date();
  const timestamp = now.toISOString().replace(/[:.]/g, '-').slice(0, 23);
  // 结果示例：2026-03-23T15-20-14-123
  
  // 净化参数（只保留安全字符）
  const safePlatform = sanitize(platform || 'unknown');
  const safeCaseId = sanitize(caseId);
  const safeDeviceId = sanitize(deviceId || 'unknown');
  
  // 构造目录名：{platform}_{caseId}_{deviceId}_{timestamp}
  const dirName = `${safePlatform}_${safeCaseId}_${safeDeviceId}_${timestamp}`;
  
  // 完整路径
  const dirPath = path.resolve(process.cwd(), TEST_INTERMEDIATES_BASE, AI_UI_TEST_DIR, dirName);
  
  // 确保目录存在
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
  }
  
  return {
    dirPath,
    logFilePath: path.join(dirPath, 'device.log'),
    perfFilePath: path.join(dirPath, 'performance.json'),
    executionChainPath: path.join(dirPath, 'execution_chain.md'),
    maestroYamlPath: path.join(dirPath, 'maestro.yaml'),
    pageDiagnosticsPath: path.join(dirPath, 'page_diagnostics.json'),
    reportPath: path.join(dirPath, 'report.html'),
  };
}

/**
 * 将 Midscene 生成的报告复制到运行目录
 * @returns 复制后的路径，如果复制失败返回原路径
 */
export function copyReportToRunDir(srcReportPath: string, destReportPath: string): string {
  try {
    if (srcReportPath && fs.existsSync(srcReportPath)) {
      // 确保目标目录存在
      const destDir = path.dirname(destReportPath);
      if (!fs.existsSync(destDir)) {
        fs.mkdirSync(destDir, { recursive: true });
      }
      fs.copyFileSync(srcReportPath, destReportPath);
      return destReportPath;
    }
  } catch (e) {
    // 复制失败，返回原路径
  }
  return srcReportPath;
}
