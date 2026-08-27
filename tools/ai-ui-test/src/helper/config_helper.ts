import { homedir } from 'os';
import type { TModelConfig } from '@midscene/shared/env';
import { ReturnAsResultError } from '../types.js';

/**
 * 展开路径中的 ~ 和 $HOME 符号
 */
function expandPath(path: string): string {
  if (!path) return path;
  return path
    .replace(/^~(?=$|\/|\\)/, homedir())
    .replace(/\$HOME/g, homedir());
}

/**
 * 检查是否使用环境变量配置（跳过 acoder-cli-server 认证）
 * 支持两种环境变量前缀：
 *   - MIDSCENE_MODEL_* （Midscene 原生格式，优先级最高）
 *   - ANTHROPIC_*      （Anthropic 兼容格式，如 DashScope 代理）
 *
 * 当 MIDSCENE_MODEL_API_KEY 或 ANTHROPIC_API_KEY 被设置时，
 * 自动跳过 Cookie 认证流程，直接使用环境变量构建模型配置。
 */
function getEnvModelConfig(): TModelConfig | null {
  const apiKey = process.env.MIDSCENE_MODEL_API_KEY || process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return null;

  const baseUrl = process.env.MIDSCENE_MODEL_BASE_URL || process.env.ANTHROPIC_BASE_URL || '';
  const modelName = process.env.MIDSCENE_MODEL_NAME || process.env.ANTHROPIC_MODEL || '';
  const runDir = process.env.MIDSCENE_RUN_DIR || '~/.cache/midscene_run';

  // 推断 modelFamily（必须为 Midscene 支持的值）：
  //   - MIDSCENE_MODEL_FAMILY 显式设置 → 使用该值
  //   - 未设置 → 留空，由 Midscene 使用默认行为
  //
  // Midscene 支持的 modelFamily 值：
  //   qwen2.5-vl, qwen3-vl, qwen3.5, doubao-vision, doubao-seed,
  //   gemini, gpt-5, vlm-ui-tars, vlm-ui-tars-doubao, vlm-ui-tars-doubao-1.5,
  //   glm-v, auto-glm, auto-glm-multilingual
  const modelFamily = process.env.MIDSCENE_MODEL_FAMILY || '';

  console.log('[INFO] 检测到环境变量模型配置，跳过 acoder-cli-server 认证');
  console.log('[INFO] 模式: 环境变量');
  console.log('[INFO] Base URL:', baseUrl);
  console.log('[INFO] 模型:', modelName);
  if (modelFamily) {
    console.log('[INFO] Model Family:', modelFamily);
  }

  const config: TModelConfig = {
    MIDSCENE_MODEL_API_KEY: apiKey,
    MIDSCENE_MODEL_BASE_URL: baseUrl,
    MIDSCENE_MODEL_NAME: modelName,
    MIDSCENE_MODEL_FAMILY: modelFamily,
    MIDSCENE_RUN_DIR: expandPath(runDir),
  };

  return config;
}

/**
 * 创建 AI 模型配置
 * 返回用于 createMobileAgent/createWebAgent 的 TModelConfig 参数
 *
 * 优先级：
 *   1. 环境变量（MIDSCENE_MODEL_API_KEY / ANTHROPIC_API_KEY）→ 跳过认证
 *   2. acoder-cli-server Cookie 认证 → 原有流程
 */
export async function createModelConfig(): Promise<TModelConfig> {
  const envConfig = getEnvModelConfig();
  if (envConfig) {
    return envConfig;
  }
  throw new ReturnAsResultError('未配置模型环境变量（MIDSCENE_MODEL_API_KEY），请在 evalapp.yaml 中配置模型信息');
}
