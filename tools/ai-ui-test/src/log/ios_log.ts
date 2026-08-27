import { spawn, ChildProcess, execSync } from 'child_process';
import { logger } from '../helper/logger.js';

/** 检测命令是否可用 */
function isCommandAvailable(cmd: string): boolean {
  try {
    execSync(`which ${cmd}`, { stdio: 'pipe' });
    return true;
  } catch {
    return false;
  }
}

/** 启动 iOS 日志捕获进程，不可用时返回 null */
export function startLogProcess(deviceId: string, filter?: string): ChildProcess | null {
  // 优先使用 idevicesyslog（真机）
  if (isCommandAvailable('idevicesyslog')) {
    const args = ['-u', deviceId];
    return spawn('idevicesyslog', args);
  }

  // 尝试模拟器方式
  try {
    return spawn('xcrun', ['simctl', 'spawn', deviceId, 'log', 'stream', '--style', 'compact']);
  } catch (e) {
    logger.warn('iOS 日志采集不可用：idevicesyslog 未安装且 xcrun simctl 失败');
    return null;
  }
}
