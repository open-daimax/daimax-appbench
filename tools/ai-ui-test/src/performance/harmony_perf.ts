import { execFileSync } from 'child_process';
import type { PerfSample } from './perf_collector.js';
import { logger } from '../helper/logger.js';

/**
 * 校验参数安全性（防止命令注入）
 */
function sanitizeParam(param: string): string {
  // 移除可能导致命令注入的特殊字符
  return param.replace(/[;&|`$"'\\<>(){}\[\]\n\r]/g, '');
}

/** 单次采样 Harmony 设备的 CPU 和内存占用 */
export async function sampleOnce(deviceId: string, packageName: string): Promise<PerfSample> {
  const sample: PerfSample = { timestamp: Date.now() };

  // 校验参数
  const safeDeviceId = sanitizeParam(deviceId);
  const safePackageName = sanitizeParam(packageName);

  // packageName 为空时跳过采集
  if (!safePackageName) {
    return sample;
  }

  // 先获取 PID
  let pid: string | undefined;
  try {
    const psOutput = execFileSync('hdc', [
      '-t', safeDeviceId,
      'shell', 'ps', '-ef'
    ], { encoding: 'utf-8', timeout: 5000, stdio: 'pipe' });

    // 在 JS 中过滤包含 packageName 的行，排除 grep 进程本身
    const lines = psOutput.split('\n');
    const processLine = lines.find(line =>
      line.includes(safePackageName) && !line.includes('grep')
    );

    if (processLine) {
      // ps -ef 输出第二列是 PID
      const parts = processLine.trim().split(/\s+/);
      if (parts.length > 1) {
        pid = parts[1];
      }
    }
  } catch {
    return sample;
  }

  if (!pid || !/^\d+$/.test(pid)) {
    return sample;
  }

  // 并行执行 CPU 和内存采集
  const cpuPromise = (async () => {
    try {
      const cpuOutput = execFileSync('hdc', [
        '-t', safeDeviceId,
        'shell', 'hidumper', '--cpuusage', '--pid', pid
      ], { encoding: 'utf-8', timeout: 5000, stdio: 'pipe' });

      const match = cpuOutput.match(/(\d+(?:\.\d+)?)%/);
      if (match) {
        return parseFloat(match[1]);
      }
    } catch {
      // 静默失败
    }
    return undefined;
  })();

  const memPromise = (async () => {
    try {
      const memOutput = execFileSync('hdc', [
        '-t', safeDeviceId,
        'shell', 'hidumper', '--mem', pid
      ], { encoding: 'utf-8', timeout: 5000, stdio: 'pipe' });

      const match = memOutput.match(/Total\s+(?:PSS|RSS)[\s:]+(\d+)/i);
      if (match) {
        return Math.round(parseInt(match[1]) / 1024 * 100) / 100; // KB -> MB
      }
    } catch {
      // 静默失败
    }
    return undefined;
  })();

  const [cpuUsage, memoryUsage] = await Promise.all([cpuPromise, memPromise]);
  sample.cpuUsage = cpuUsage;
  sample.memoryUsage = memoryUsage;

  return sample;
}
