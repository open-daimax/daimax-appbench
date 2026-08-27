import { execFileSync } from 'child_process';
import type { PerfSample } from './perf_collector.js';

/**
 * 校验参数安全性（防止命令注入）
 */
function sanitizeParam(param: string): string {
  // 移除可能导致命令注入的特殊字符
  return param.replace(/[;&|`$"'\\<>(){}\[\]\n\r]/g, '');
}

// PID 缓存: key = "deviceId:packageName", value = pid
const pidCache = new Map<string, string>();

/** 获取 PID（带缓存） */
function getPid(deviceId: string, packageName: string): string | undefined {
  const cacheKey = `${deviceId}:${packageName}`;
  
  // 先检查缓存
  const cachedPid = pidCache.get(cacheKey);
  if (cachedPid) {
    // 验证缓存的 PID 是否仍然有效
    try {
      const checkOutput = execFileSync('adb', [
        '-s', deviceId,
        'shell', 'ps', '-p', cachedPid, '-o', 'PID'
      ], { encoding: 'utf-8', timeout: 1000, stdio: 'pipe' });
      // 如果命令成功且输出包含 PID，说明进程仍然存在
      if (checkOutput.includes(cachedPid)) {
        return cachedPid;
      }
    } catch {
      // PID 已失效，从缓存中删除
      pidCache.delete(cacheKey);
    }
  }

  // 缓存未命中或失效，重新查询
  try {
    const psOutput = execFileSync('adb', [
      '-s', deviceId,
      'shell', 'ps', '-A', '-o', 'PID,NAME'
    ], { encoding: 'utf-8', timeout: 2000, stdio: 'pipe' });

    const lines = psOutput.split('\n');
    const processLine = lines.find(line => line.includes(packageName));
    if (processLine) {
      const parts = processLine.trim().split(/\s+/);
      if (parts.length > 1 && /^\d+$/.test(parts[0])) {
        const pid = parts[0];
        // 存入缓存
        pidCache.set(cacheKey, pid);
        return pid;
      }
    }
  } catch {
    // 查询失败
  }
  return undefined;
}

/** 单次采样 Android 设备的 CPU 和内存占用 */
export async function sampleOnce(deviceId: string, packageName: string): Promise<PerfSample> {
  const sample: PerfSample = { timestamp: Date.now() };

  // 校验参数
  const safeDeviceId = sanitizeParam(deviceId);
  const safePackageName = sanitizeParam(packageName);

  // packageName 为空时跳过采集
  if (!safePackageName) {
    return sample;
  }

  // 获取 PID（带缓存）
  const pid = getPid(safeDeviceId, safePackageName);
  if (!pid) {
    return sample;
  }

  // 并行执行 CPU 和内存采集
  const cpuPromise = (async () => {
    try {
      // 使用 ps -p <pid> -o %CPU 获取指定进程的 CPU
      const cpuOutput = execFileSync('adb', [
        '-s', safeDeviceId,
        'shell', 'ps', '-p', pid, '-o', 'PID,%CPU'
      ], { encoding: 'utf-8', timeout: 2000, stdio: 'pipe' });

      // 解析输出找到对应 PID 的 CPU 占用
      const lines = cpuOutput.split('\n');
      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith(pid)) {
          const parts = trimmed.split(/\s+/);
          if (parts.length >= 2) {
            const cpuValue = parseFloat(parts[1]);
            if (!isNaN(cpuValue)) {
              return cpuValue;
            }
          }
        }
      }
    } catch {
      // 静默失败
    }
    return undefined;
  })();

  const memPromise = (async () => {
    try {
      const memOutput = execFileSync('adb', [
        '-s', safeDeviceId,
        'shell', 'dumpsys', 'meminfo', pid
      ], { encoding: 'utf-8', timeout: 2000, stdio: 'pipe' });

      // 查找 "TOTAL PSS:" 或 "TOTAL" 行（支持带冒号和不带冒号的格式）
      const lines = memOutput.split('\n');
      for (const line of lines) {
        // 匹配 "TOTAL PSS: 123456" 或 "TOTAL   123456"（冒号可选，多个空格）
        const match = line.match(/^\s*TOTAL(?:\s+PSS)?[:\s]+(\d+)/);
        if (match) {
          return Math.round(parseInt(match[1]) / 1024 * 100) / 100; // KB -> MB
        }
      }
    } catch {
      // 静默失败
    }
    return undefined;
  })();

  // 等待两个采集完成
  const [cpuUsage, memoryUsage] = await Promise.all([cpuPromise, memPromise]);
  sample.cpuUsage = cpuUsage;
  sample.memoryUsage = memoryUsage;

  return sample;
}
