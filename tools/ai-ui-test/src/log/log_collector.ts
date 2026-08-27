import type { ChildProcess } from 'child_process';
import type { Platform } from '../types.js';
import { logger } from '../helper/logger.js';
import * as fs from 'fs';
import * as path from 'path';

export class DeviceLogCollector {
  private buffer: string[] = [];
  private process: ChildProcess | null = null;
  private startTime: number = 0;

  /** 启动日志捕获（后台子进程） */
  async start(platform: Platform, deviceId: string, filter?: string): Promise<void> {
    this.buffer = [];
    this.startTime = Date.now();

    try {
      switch (platform) {
        case 'android': {
          const { startLogProcess } = await import('./android_log.js');
          this.process = startLogProcess(deviceId, filter);
          break;
        }
        case 'harmony': {
          const { startLogProcess } = await import('./harmony_log.js');
          this.process = startLogProcess(deviceId, filter);
          break;
        }
        case 'ios': {
          const { startLogProcess } = await import('./ios_log.js');
          this.process = startLogProcess(deviceId, filter);
          break;
        }
        case 'web': {
          // Web 使用 WebLogCollector，不通过此类
          logger.info('Web 平台请使用 WebLogCollector');
          return;
        }
        default:
          logger.warn(`不支持的平台日志采集: ${platform}`);
          return;
      }

      if (this.process) {
        this.process.stdout?.on('data', (data: Buffer) => {
          const lines = data.toString().split('\n').filter(l => l.trim());
          this.buffer.push(...lines);
        });
        this.process.stderr?.on('data', (data: Buffer) => {
          // 有些平台（如 logcat）可能通过 stderr 输出
          const lines = data.toString().split('\n').filter(l => l.trim());
          this.buffer.push(...lines);
        });
        this.process.on('error', (err) => {
          logger.warn(`日志采集进程出错: ${err.message}`);
        });
        logger.info(`日志采集已启动 [${platform}] deviceId=${deviceId}`);
      }
    } catch (error) {
      logger.warn(`日志采集启动失败: ${error}`);
    }
  }

  /** 停止捕获 */
  async stop(): Promise<void> {
    if (this.process) {
      try {
        this.process.kill('SIGTERM');
        // 等待进程退出
        await new Promise<void>((resolve) => {
          const timeout = setTimeout(() => {
            this.process?.kill('SIGKILL');
            resolve();
          }, 3000);
          this.process?.on('exit', () => {
            clearTimeout(timeout);
            resolve();
          });
        });
      } catch (error) {
        logger.warn(`停止日志采集进程出错: ${error}`);
      }
      this.process = null;
    }
  }

  /** 保存日志到文件，返回文件路径 */
  saveToFile(filePath: string): string {
    if (this.buffer.length === 0) {
      logger.info('没有采集到日志数据，跳过保存');
      return '';
    }

    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    const lineCount = this.buffer.length;
    fs.writeFileSync(filePath, this.buffer.join('\n'), 'utf-8');
    logger.info(`设备日志已保存: ${filePath} (${lineCount} 行)`);
    return filePath;
  }

  /** 获取已采集的日志内容（供断言用） */
  getCollectedLogs(): string[] {
    return [...this.buffer];
  }
}

/** 日志断言结果 */
export interface LogAssertResult {
  passed: boolean;
  matchedLine?: string;
  totalLines: number;
}

/**
 * 对已采集的日志执行正则断言
 * @param logs 已采集的日志行
 * @param pattern 正则表达式字符串
 * @returns { passed: boolean; matchedLine?: string; totalLines: number }
 */
export function assertLogContains(
  logs: string[],
  pattern: string
): LogAssertResult {
  const regex = new RegExp(pattern);
  const totalLines = logs.length;
  const matchedLine = logs.find(line => regex.test(line));
  return {
    passed: !!matchedLine,
    matchedLine,
    totalLines,
  };
}
