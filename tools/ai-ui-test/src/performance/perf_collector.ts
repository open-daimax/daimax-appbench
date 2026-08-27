import type { Platform } from '../types.js';
import { logger } from '../helper/logger.js';
import * as fs from 'fs';
import * as path from 'path';

export interface PerfSample {
  timestamp: number;
  cpuUsage?: number;
  memoryUsage?: number;
}

export interface PerfSummary {
  sampleCount: number;
  duration: number;
  cpu?: { peak: number; avg: number };
  memory?: { peak: number; avg: number };
  samples: PerfSample[];
}

type SampleFn = (deviceId: string, packageName: string) => Promise<PerfSample>;

export class DevicePerfCollector {
  private timer: NodeJS.Timeout | null = null;
  private samples: PerfSample[] = [];
  private startTime: number = 0;
  private collecting: boolean = false;

  /** 启动周期性采集 */
  async start(platform: Platform, deviceId: string, packageName: string, intervalMs: number = 2000): Promise<void> {
    this.samples = [];
    this.startTime = Date.now();
    this.collecting = true;

    let sampleFn: SampleFn | null = null;

    try {
      switch (platform) {
        case 'android': {
          const mod = await import('./android_perf.js');
          sampleFn = mod.sampleOnce;
          break;
        }
        case 'harmony': {
          const mod = await import('./harmony_perf.js');
          sampleFn = mod.sampleOnce;
          break;
        }
        case 'ios': {
          const mod = await import('./ios_perf.js');
          sampleFn = mod.sampleOnce;
          break;
        }
        default:
          logger.warn(`不支持的平台性能采集: ${platform}`);
          return;
      }
    } catch (error) {
      logger.warn(`性能采集模块加载失败: ${error}`);
      return;
    }

    if (!sampleFn) return;

    // 使用递归 setTimeout 替代 setInterval，避免采样重叠
    const scheduleNext = () => {
      this.timer = setTimeout(async () => {
        if (!this.collecting || !sampleFn) return;
        try {
          const sample = await sampleFn(deviceId, packageName);
          this.samples.push(sample);
        } catch {
          // 静默失败
        }
        // 继续下一次调度
        scheduleNext();
      }, intervalMs);
    };

    // 立即采样一次
    try {
      const sample = await sampleFn(deviceId, packageName);
      this.samples.push(sample);
    } catch {
      // 静默失败
    }

    // 然后定时采样
    scheduleNext();
    logger.info(`性能采集已启动 [${platform}] packageName=${packageName}, interval=${intervalMs}ms`);
  }

  /** 停止采集 */
  async stop(): Promise<void> {
    this.collecting = false;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    logger.info(`性能采集已停止，共采集 ${this.samples.length} 个样本`);
  }

  /** 计算统计摘要 */
  getSummary(): PerfSummary {
    const duration = this.startTime ? Date.now() - this.startTime : 0;
    const summary: PerfSummary = {
      sampleCount: this.samples.length,
      duration,
      samples: [...this.samples],
    };

    // 计算 CPU 统计
    const cpuValues = this.samples.map(s => s.cpuUsage).filter((v): v is number => v !== undefined);
    if (cpuValues.length > 0) {
      summary.cpu = {
        peak: Math.max(...cpuValues),
        avg: Math.round(cpuValues.reduce((a, b) => a + b, 0) / cpuValues.length * 100) / 100,
      };
    }

    // 计算内存统计
    const memValues = this.samples.map(s => s.memoryUsage).filter((v): v is number => v !== undefined);
    if (memValues.length > 0) {
      summary.memory = {
        peak: Math.max(...memValues),
        avg: Math.round(memValues.reduce((a, b) => a + b, 0) / memValues.length * 100) / 100,
      };
    }

    return summary;
  }

  /** 保存到文件（含原始数据 + 摘要），返回文件路径 */
  saveToFile(filePath: string): string {
    if (this.samples.length === 0) {
      logger.info('没有性能采样数据，跳过保存');
      return '';
    }

    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    const summary = this.getSummary();
    const data = {
      summary: {
        sampleCount: summary.sampleCount,
        duration: summary.duration,
        cpu: summary.cpu,
        memory: summary.memory,
      },
      samples: summary.samples,
    };

    fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf-8');
    logger.info(`性能数据已保存: ${filePath} (${summary.sampleCount} 个样本)`);
    return filePath;
  }
}
