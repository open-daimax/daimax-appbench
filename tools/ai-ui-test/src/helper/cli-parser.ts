/**
 * CLI 参数解析模块
 * 
 * 使用 commander.js 实现混合模式的参数解析：
 * - 位置参数：测试用例（必选）
 * - 命名参数：平台、应用名、包名等（可选）
 */

import { Command } from 'commander';
import type { TestCase } from '../types.js';

/**
 * 创建并配置 CLI 程序
 */
export function createCliProgram(): Command {
  const program = new Command();

  program
    .name('ai-ui-test')
    .description('AI-powered UI testing for mobile applications')
    .argument('<steps>', 'UI 操作步骤描述（自然语言）')
    .argument('<assertion>', '断言验证描述（自然语言）')
    .requiredOption('-c, --case-id <id>', '用例 ID，用于缓存标识（必填）')
    .option('-p, --platform <type>', '平台类型 (android|ios|harmony|web)，默认自动检测')
    .option('-a, --app <name>', '应用名称')
    .option('-P, --package <id>', '包名/Bundle ID')
    .option('-d, --device-id <id>', '指定设备 ID')
    .option('-s, --scheme <url>', '启动 scheme/deeplink，用于启动特定页面，缩短测试链路')
    .option('-u, --url <url>', 'Web URL，指定后自动使用 Web 平台')
    .option('--headless', '使用无头模式（仅 Web 平台），默认 false')
    .option('-k, --knowledge <text>', '业务知识，帮助 AI 更准确理解测试意图')
    .option('--log-assert <regex>', '日志断言正则，断言设备日志中包含匹配行')
    .option('-v, --viewport <size>', '视口尺寸，格式: 宽x高 (如 390x844)，仅Web平台')
    .option('--verify-real-backend', '验证是否使用真实后端（仅 Web 平台，通过网络请求监听）')
    .helpOption('-h, --help', '显示帮助信息');

  return program;
}

/**
 * 解析命令行参数
 * 
 * @returns 解析后的测试用例
 */
export function parseCliArguments(): TestCase {
  const program = createCliProgram();
  
  // 解析参数
  program.parse();
  
  // 获取位置参数（UI 操作步骤和断言）
  const [steps, assertion] = program.args;
  
  // 获取命名参数
  const options = program.opts();
  
  return {
    caseId: options.caseId,
    steps,
    assertion,
    knowledge: options.knowledge,
    platform: options.platform,
    appName: options.app,
    packageName: options.package,
    deviceId: options.deviceId,
    scheme: options.scheme,
    url: options.url,
    headless: options.headless,
    logAssert: options.logAssert,
    viewport: options.viewport,
    verifyRealBackend: options.verifyRealBackend,
  };
}
