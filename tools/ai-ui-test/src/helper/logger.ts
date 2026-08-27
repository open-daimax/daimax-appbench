/**
 * 日志系统
 * 提供统一的日志输出接口
 */

type LogLevel = 'silent' | 'error' | 'warn' | 'info' | 'debug';

const LOG_LEVELS: Record<LogLevel, number> = {
  silent: 0,
  error: 1,
  warn: 2,
  info: 3,
  debug: 4,
};

const LOG_LEVEL = (process.env.LOG_LEVEL as LogLevel) || 'info';
const DEBUG = process.env.DEBUG === 'true';

/**
 * 判断是否应该输出指定级别的日志
 */
function shouldLog(level: LogLevel): boolean {
  const currentLevel = DEBUG ? LOG_LEVELS.debug : LOG_LEVELS[LOG_LEVEL];
  return LOG_LEVELS[level] <= currentLevel;
}

/**
 * 输出日志到 stderr
 */
function log(level: LogLevel, message: string): void {
  if (shouldLog(level)) {
    const timestamp = new Date().toISOString();
    console.error(`[${timestamp}] [${level.toUpperCase()}] ${message}`);
  }
}

/**
 * 日志工具对象
 */
export const logger = {
  debug: (message: string) => log('debug', message),
  info: (message: string) => log('info', message),
  warn: (message: string) => log('warn', message),
  error: (message: string, error?: unknown) => {
    const errorMsg = error ? `${message}: ${error}` : message;
    log('error', errorMsg);
  },
};