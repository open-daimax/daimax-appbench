import type { Page, ConsoleMessage } from 'playwright';

/** Web 平台日志采集器（基于 Playwright page.on('console')） */
export class WebLogCollector {
  private buffer: string[] = [];
  private handler: ((msg: ConsoleMessage) => void) | null = null;
  private page: Page | null = null;

  /** 注册到 Playwright page 上 */
  attach(page: Page): void {
    this.page = page;
    this.handler = (msg: ConsoleMessage) => {
      const text = `[${msg.type()}] ${msg.text()}`;
      this.buffer.push(`${new Date().toISOString()} ${text}`);
    };
    page.on('console', this.handler);
  }

  /** 获取采集的日志 */
  getCollectedLogs(): string[] {
    return [...this.buffer];
  }

  /** 停止采集 */
  detach(): void {
    if (this.page && this.handler) {
      this.page.removeListener('console', this.handler);
    }
    this.handler = null;
    this.page = null;
  }
}
