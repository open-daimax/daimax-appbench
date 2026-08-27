// 版本显示配置
export const VERSION_DISPLAY = {
  V1: 'V1',
  V1plus: 'V1+',
  V2: 'V2',
}

// 版本排序顺序
export const VERSION_ORDER = ['V1', 'V1plus', 'V2']

// 从样本数组中提取所有版本（自动发现，按预定义顺序排列）
export function extractVersions(samples) {
  const versions = [...new Set(samples.map(s => s.dataset_version).filter(Boolean))]
  // 按预定义顺序排列，未知版本放后面
  return versions.sort((a, b) => {
    const ia = VERSION_ORDER.indexOf(a)
    const ib = VERSION_ORDER.indexOf(b)
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib)
  })
}

// 按版本过滤样本（支持单选字符串模式和多选数组模式）
export function filterByVersion(samples, selectedVersions) {
  // 无数据时不过滤
  if (!samples || samples.length === 0) return samples
  // 单选模式：字符串具体版本值
  if (typeof selectedVersions === 'string') {
    if (!selectedVersions) return samples
    // 如果样本数据中没有任何 dataset_version 字段，不过滤
    const hasVersionField = samples.some(s => s.dataset_version)
    if (!hasVersionField) return samples
    return samples.filter(s => s.dataset_version === selectedVersions)
  }
  // 多选模式：数组
  if (!selectedVersions || selectedVersions.length === 0) return samples
  // 如果样本数据中没有任何 dataset_version 字段，不过滤
  const hasVersionField = samples.some(s => s.dataset_version)
  if (!hasVersionField) return samples
  return samples.filter(s => selectedVersions.includes(s.dataset_version))
}
