import { spawn, ChildProcess } from 'child_process';

/** 启动 Android logcat 日志捕获进程 */
export function startLogProcess(deviceId: string, filter?: string): ChildProcess {
  const args = ['-s', deviceId, 'logcat', '-v', 'time'];
  if (filter) {
    args.push(filter);
  }
  return spawn('adb', args);
}
