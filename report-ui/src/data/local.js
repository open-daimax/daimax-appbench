/**
 * 本地报告数据源
 *
 * 报告页在 Web 控制台里通过 HTTP API 取数据，在本地单文件报告里则全部来自
 * 生成时注入的 window.__REPORT_DATA__（由 evalapp 的 Reporter 写入）。
 * 本模块是这些注入数据的唯一读取入口，报告页组件不再区分"静态/非静态"。
 *
 * 文件类资源（截图、e2e 报告 HTML）以工作区根目录相对路径给出——report.html
 * 就在工作区根目录，浏览器可直接按相对路径打开。
 */

/** 注入的报告数据；缺失时返回 null，由调用方降级 */
export function getReportData() {
  if (typeof window === 'undefined') return null
  return window.__REPORT_DATA__ ?? null
}

/** 工作区目录名（页面标题与展示用） */
export function getWorkspaceId() {
  const data = getReportData()
  return data?.static_workspace_id || data?.meta?.run_id || 'local'
}

/**
 * 样本截图清单：[{ filename, url, platform, tc_id, step }]
 * url 已是工作区相对路径，可直接作为 <img src>。
 * @param {string} sampleId 样本 ID
 * @param {string[]} [platforms] 平台白名单，为空则不过滤
 */
export function getSampleScreenshots(sampleId, platforms) {
  const all = getReportData()?.static_screenshots?.[sampleId]
  if (!Array.isArray(all)) return []
  if (!Array.isArray(platforms) || platforms.length === 0) return all
  return all.filter(s => !s.platform || platforms.includes(s.platform))
}

/** 某样本某平台的截图 URL（按文件名精确匹配，找不到返回 null） */
export function getScreenshotUrl(sampleId, filename) {
  if (!sampleId || !filename) return null
  const hit = getSampleScreenshots(sampleId).find(s => s.filename === filename)
  return hit ? hit.url : `${sampleId}/screenshots/${filename}`
}

/** 美观度评测 trace（关键截图与五维明细），无数据返回 null */
export function getAestheticsTrace(sampleId, platform) {
  const traces = getReportData()?.static_aesthetics_traces
  if (!traces || !sampleId) return null
  const byPlatform = traces[sampleId]
  if (!byPlatform) return null
  return byPlatform[platform] ?? null
}

/** 指令历史列表（工作区 command_history.json） */
export function getCommandHistory() {
  const list = getReportData()?.static_command_history
  return Array.isArray(list) ? list : []
}

/** 样本集类别清单（用于筛选栏分组与中文标题） */
export function getDatasetCategories() {
  const list = getReportData()?.static_dataset_info?.categories
  return Array.isArray(list) ? list : []
}

/** 样本需求元数据：{ title, app_type, requirement, core_functions, constraints } */
export function getSampleMeta(sampleId) {
  return getReportData()?.static_dataset_info?.samples?.[sampleId] ?? null
}

/**
 * 测试用例定义（测试步骤 / 预期结果）
 * 数据集按平台分文件存放，缺平台专属定义时回退 default。
 */
export function getTestCaseDefs(sampleId, platform) {
  const byPlatform = getReportData()?.static_dataset_info?.test_cases?.[sampleId]
  if (!byPlatform) return []
  const defs = byPlatform[platform] || byPlatform.default || []
  return Array.isArray(defs) ? defs : []
}

/**
 * e2e 报告 HTML 的可打开链接
 * report_path 由生成侧统一改写为工作区相对路径；仍是绝对路径的说明导出目录里
 * 没有对应文件，返回 null 让调用方隐藏入口。
 */
export function getE2eReportUrl(reportPath) {
  if (!reportPath || typeof reportPath !== 'string') return null
  if (reportPath.startsWith('/')) return null
  return reportPath
}

/** 工作区内任意文件的可打开链接（如执行报告 execution_report_path） */
export function getWorkspaceFileUrl(relPath) {
  if (!relPath || typeof relPath !== 'string' || relPath.startsWith('/')) return null
  return relPath
}
