import { execFileSync } from 'child_process';
import type { PerfSample } from './perf_collector.js';
import { logger } from '../helper/logger.js';

/**
 * iOS 性能采集模块
 * 
 * 采集策略：
 * 1. 优先通过 WDA 的 /wda/performanceData 接口获取（需要 WDA 已运行）
 * 2. 降级方案：通过 devicectl 命令获取基础设备信息
 * 
 * 注意：iOS 平台的性能采集受限于 Apple 的安全策略，
 * 精确的 CPU/内存数据需要 Instruments/xctrace 工具链，
 * 此处通过 WDA 获取的是应用级别的近似数据。
 */

/** WDA 设备地址（默认 localhost:8100） */
let wdaBaseUrl = 'http://localhost:8100';

/**
 * 设置 WDA 基础 URL（用于自定义端口）
 */
export function setWdaBaseUrl(url: string): void {
  wdaBaseUrl = url;
}

/**
 * 通过 WDA 获取应用性能数据
 * 使用 /wda/performanceData 端点
 */
async function fetchPerfFromWDA(packageName: string): Promise<{ cpu?: number; memory?: number }> {
  try {
    const response = await fetch(`${wdaBaseUrl}/wda/performanceData`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bundleId: packageName,
        pid: 'current',
        profileType: 'all',
      }),
      signal: AbortSignal.timeout(5000),
    });

    if (!response.ok) {
      return {};
    }

    const data = await response.json() as {
      value?: {
        cpu?: { value?: number };
        memory?: { value?: number; physFootprint?: number };
      };
    };

    const result: { cpu?: number; memory?: number } = {};

    if (data.value?.cpu?.value !== undefined) {
      result.cpu = data.value.cpu.value;
    }

    if (data.value?.memory?.physFootprint !== undefined) {
      // physFootprint 单位为 bytes，转换为 MB
      result.memory = Math.round(data.value.memory.physFootprint / (1024 * 1024) * 100) / 100;
    } else if (data.value?.memory?.value !== undefined) {
      // value 单位为 bytes，转换为 MB
      result.memory = Math.round(data.value.memory.value / (1024 * 1024) * 100) / 100;
    }

    return result;
  } catch {
    return {};
  }
}

/**
 * 降级方案：通过 ios-deploy 或 devicectl 获取基础性能信息
 * 适用于 WDA performanceData 不可用的场景
 */
async function fetchPerfFromDeviceCtl(deviceId: string, packageName: string): Promise<{ cpu?: number; memory?: number }> {
  try {
    // 尝试通过 devicectl 获取进程信息（macOS 14.4+ / Xcode 15.3+）
    const output = execFileSync('xcrun', [
      'devicectl', 'device', 'info', 'processes',
      '--device', deviceId,
      '--quiet', '--json-output', '/dev/stdout',
    ], { encoding: 'utf-8', timeout: 10000, stdio: 'pipe' });

    const data = JSON.parse(output) as {
      result?: {
        runningProcesses?: Array<{
          executable?: string;
          memoryUsage?: number;
          cpuUsage?: number;
        }>;
      };
    };

    const processes = data.result?.runningProcesses || [];
    const targetProcess = processes.find(p => 
      p.executable?.includes(packageName) || p.executable?.includes(packageName.split('.').pop() || '')
    );

    if (targetProcess) {
      return {
        cpu: targetProcess.cpuUsage,
        memory: targetProcess.memoryUsage 
          ? Math.round(targetProcess.memoryUsage / (1024 * 1024) * 100) / 100
          : undefined,
      };
    }
  } catch {
    // devicectl 不可用或执行失败，静默处理
  }
  return {};
}

/** 单次采样 iOS 设备性能 */
export async function sampleOnce(deviceId: string, packageName: string): Promise<PerfSample> {
  const sample: PerfSample = { timestamp: Date.now() };

  // packageName 为空时跳过采集
  if (!packageName) {
    return sample;
  }

  // 解析 deviceId 获取 WDA 地址
  if (deviceId.includes(':')) {
    const [host, port] = deviceId.split(':');
    wdaBaseUrl = `http://${host || 'localhost'}:${port || '8100'}`;
  }

  // 优先使用 WDA 接口
  const wdaResult = await fetchPerfFromWDA(packageName);
  if (wdaResult.cpu !== undefined || wdaResult.memory !== undefined) {
    sample.cpuUsage = wdaResult.cpu;
    sample.memoryUsage = wdaResult.memory;
    return sample;
  }

  // 降级：使用 devicectl
  const deviceCtlResult = await fetchPerfFromDeviceCtl(deviceId, packageName);
  sample.cpuUsage = deviceCtlResult.cpu;
  sample.memoryUsage = deviceCtlResult.memory;

  return sample;
}
