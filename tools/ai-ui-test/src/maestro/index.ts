/**
 * Maestro 模块入口
 * 导出核心功能和辅助函数
 */

import { writeFile, mkdir } from 'fs/promises';
import { dirname } from 'path';
import { extractReportJsonFromHtml } from '../helper/midscene_report_helper.js';
import { MaestroConverter } from './converter.js';
import type { ConversionOptions, ConversionResult } from './types.js';

// ============================================================================
// 核心转换器
// ============================================================================

export { MaestroConverter } from './converter.js';

// ============================================================================
// 辅助函数（处理完整流程）
// ============================================================================

/**
 * 从 HTML 报告转换为 Maestro YAML 并保存
 * 
 * @param htmlPath - HTML 报告路径
 * @param outputPath - 输出 YAML 文件路径
 * @param options - 转换选项
 * @returns 转换结果
 */
export async function convertHtmlToYaml(
  htmlPath: string,
  outputPath: string,
  options: ConversionOptions
): Promise<ConversionResult> {
  try {
    // 1. 从 HTML 提取 JSON
    const reportData = await extractReportJsonFromHtml(htmlPath);
    
    // 2. 转换为 YAML
    const converter = new MaestroConverter(reportData, options);
    const result = converter.convert();
    
    if (!result.success || !result.yaml) {
      return result;
    }
    
    // 3. 保存 YAML 文件
    await saveYaml(result.yaml, outputPath);
    
    return result;
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : String(error)
    };
  }
}


/**
 * 保存 YAML 内容到文件
 */
async function saveYaml(yaml: string, outputPath: string): Promise<void> {
  const dir = dirname(outputPath);
  await mkdir(dir, { recursive: true });
  await writeFile(outputPath, yaml, 'utf-8');
}

// ============================================================================
// 测试执行（外部使用）
// ============================================================================

export { 
  runMaestroTest,
  checkMaestroInstalled,
  executeMaestroTest,
  checkMaestroYaml,
  tryConvertToMaestroYaml
} from './executor.js';

// ============================================================================
// 类型定义
// ============================================================================

export type {
  ConversionOptions,
  ConversionResult,
  MaestroCommand,
  MaestroFlow,
  MidsceneAction,
  MidsceneReport
} from './types.js';