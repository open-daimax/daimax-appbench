/**
 * Midscene 报告处理辅助函数
 * 职责：从 HTML 报告中提取 JSON 数据
 */

import { readFile } from 'fs/promises';
import type { MidsceneReport } from '../maestro/types.js';

/**
 * 从 Midscene HTML 报告中提取 JSON 数据
 * 
 * @param htmlPath - HTML 报告文件路径
 * @returns 报告 JSON 数据
 */
export async function extractReportJsonFromHtml(htmlPath: string): Promise<MidsceneReport> {
  const htmlContent = await readFile(htmlPath, 'utf-8');
  
  // 查找 <script type="midscene_web_dump"> 标签
  const scriptStartTag = '<script type="midscene_web_dump">';
  const scriptEndTag = '</script>';
  
  const lastStartIndex = htmlContent.lastIndexOf(scriptStartTag);
  if (lastStartIndex === -1) {
    throw new Error('HTML 报告中未找到 midscene_web_dump 脚本标签');
  }
  
  const jsonStartIndex = lastStartIndex + scriptStartTag.length;
  const jsonEndIndex = htmlContent.indexOf(scriptEndTag, jsonStartIndex);
  
  if (jsonEndIndex === -1) {
    throw new Error('HTML 报告中的 midscene_web_dump 脚本标签未正确闭合');
  }
  
  const jsonStr = htmlContent.substring(jsonStartIndex, jsonEndIndex).trim();
  
  try {
    return JSON.parse(jsonStr) as MidsceneReport;
  } catch (error) {
    throw new Error(`解析 JSON 数据失败: ${error instanceof Error ? error.message : String(error)}`);
  }
}

/**
 * 从 JSON 文件读取报告数据
 * 
 * @param jsonPath - JSON 文件路径
 * @returns 报告 JSON 数据
 */
export async function readReportJson(jsonPath: string): Promise<MidsceneReport> {
  const content = await readFile(jsonPath, 'utf-8');
  return JSON.parse(content) as MidsceneReport;
}