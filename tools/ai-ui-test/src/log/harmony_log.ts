import { spawn, ChildProcess } from 'child_process';

/** 启动 Harmony hilog 日志捕获进程 */
export function startLogProcess(deviceId: string, filter?: string): ChildProcess {
  const args = ['-t', deviceId, 'shell', 'hilog'];
  if (filter) {
    // hilog 支持 --type 等过滤参数
    args.push(filter);
  }
  return spawn('hdc', args);
}
