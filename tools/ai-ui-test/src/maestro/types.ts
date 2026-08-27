/**
 * Maestro 转换器类型定义
 */

/**
 * Midscene 报告中的动作类型
 */
export interface MidsceneAction {
  type: string;
  thought?: string;
  param?: {
    type?: string;
    value?: string;
    position?: {
      left: number;
      top: number;
      width: number;
      height: number;
    };
    coordinate?: {
      x: number;
      y: number;
    };
    locate?: {
      description?: string;
    };
  };
  error?: string;
  timing?: {
    start: number;
    end: number;
    cost: number;
  };
}

/**
 * Midscene 报告数据结构（Maestro 转换器使用）
 */
export interface MidsceneReport {
  actions: MidsceneAction[];
  executions?: MidsceneExecution[];
  sdkVersion?: string;
  groupName?: string;
  groupDescription?: string;
}

/**
 * 执行记录（Maestro 转换器视角）
 */
export interface MidsceneExecution {
  name?: string;
  tasks?: MidsceneReportTask[];
  uiContext?: {
    shotSize?: { width: number; height: number };
  };
}

/**
 * 任务记录（Maestro 转换器视角）
 */
export interface MidsceneReportTask {
  type?: string;
  subType?: string;
  status?: string;
  thought?: string;
  error?: string | null;
  param?: {
    value?: string;
    locate?: {
      description?: string;
      center?: number[];
      rect?: { left: number; top: number; width: number; height: number };
    };
  };
  uiContext?: {
    shotSize?: { width: number; height: number };
  };
}

/**
 * Maestro 命令类型
 */
export type MaestroCommand = 
  | { tapOn: { point?: string; text?: string } }
  | { inputText: string; tapOn?: { point?: string; text?: string } }
  | { openLink: string }
  | { scroll: { direction?: string } }
  | { swipe: { direction: string; from?: { point: string }; to?: { point: string } } }
  | { assertVisible: string }
  | { extendedWaitUntil: { visible: string; timeout?: number } }
  | { runFlow: { when?: { visible?: string }; commands: MaestroCommand[] } }
  | { repeat: { times: number; commands: MaestroCommand[] } }
  | { waitForAnimationToEnd: { timeout?: number } };

/**
 * Maestro Flow 配置
 */
export interface MaestroFlow {
  appId: string;
  name?: string;
  tags?: string[];
  platform?: PlatformConfig;
  '---': MaestroCommand[];
}

/**
 * 平台配置
 */
export interface PlatformConfig {
  /** iOS 平台配置 */
  ios?: {
    /** 是否禁用动画（Cloud-only 功能） */
    disableAnimations?: boolean;
  };
  /** Android 平台配置 */
  android?: {
    /** 是否禁用动画（Cloud-only 功能） */
    disableAnimations?: boolean;
  };
}

/**
 * 转换选项（仅包含用户必须提供的参数）
 */
export interface ConversionOptions {
  /** 应用包名/Bundle ID */
  appId: string;
  /** 测试用例名称（可选，如果不提供则从报告中提取） */
  name?: string;
  /** 标签（可选） */
  tags?: string[];
  /** 是否优先使用文本选择器（可选，默认 false） */
  preferTextSelectors?: boolean;
  /** 平台配置（可选） */
  platform?: PlatformConfig;
}

/**
 * 转换结果
 */
export interface ConversionResult {
  /** 是否成功 */
  success: boolean;
  /** Maestro YAML 内容 */
  yaml?: string;
  /** 错误信息 */
  error?: string;
  /** 转换的命令数量 */
  commandCount?: number;
  /** 设备 ID（可选） */
  deviceId?: string;
}
