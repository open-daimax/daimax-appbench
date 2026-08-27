/**
 * 样本 / 样本集中文展示名工具
 *
 * 只影响用户可见的展示文案，不改变筛选 value、API 字段名、请求参数等原始英文标识。
 * 优先使用数据中已有的中文字段（sample_title / title / 样本集接口的 name），
 * 兜底映射仅覆盖无中文来源的英文标识；覆盖不到的值原样回退显示。
 */

// 英文样本集/类别标识 → 中文名的兜底映射（与 dataset/*/index.yaml 中的 name 对齐）
export const DATASET_NAME_MAP = {
  // V2 类别
  beverage: '饮品品鉴',
  collection: '收藏鉴赏',
  community: '社区互动',
  craft: '手工创作',
  creative: '灵感创作',
  dining: '餐饮美食',
  ecommerce: '电商购物',
  education: '在线教育',
  exploration: '探索发现',
  finance: '理财记账',
  games: '休闲游戏',
  health: '健康管理',
  knowledge: '知识学习',
  nature: '自然观察',
  productivity: '效率工具',
  social: '社交媒体',
  wellness: '身心健康',
  // V1 独有类别
  lifestyle: '生活方式',
  media: '资讯',
  tools: '工具',
  // 版本级样本集
  V1: 'V1 基线回归样本集',
  V1plus: 'V1+ 跨平台增强样本集',
  V2: 'V2 样本集',
  // 派生失败兜底值
  Unknown: '未知',
}

/**
 * 样本集/类别展示名：命中映射返回中文，否则原样返回（保证不显示 undefined/空白）
 */
export function getDatasetDisplayName(name) {
  if (name === null || name === undefined || name === '') return ''
  return DATASET_NAME_MAP[name] || name
}

/**
 * 样本展示名：优先中文标题（sample_title / title），无中文标题时回退 sample_id
 */
export function getSampleDisplayName(sample) {
  if (!sample) return ''
  return sample.sample_title || sample.title || sample.sample_id || ''
}
