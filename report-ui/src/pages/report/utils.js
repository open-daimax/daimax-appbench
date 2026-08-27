export function formatDuration(ms) {
  if (!ms || ms <= 0) return 'N/A'
  const totalSec = Math.floor(ms / 1000)
  const hours = Math.floor(totalSec / 3600)
  const minutes = Math.floor((totalSec % 3600) / 60)
  const seconds = totalSec % 60
  const parts = []
  if (hours > 0) parts.push(`${hours}小时`)
  if (minutes > 0) parts.push(`${minutes}分`)
  if (seconds > 0 || parts.length === 0) parts.push(`${seconds}秒`)
  return parts.join('')
}

export function formatBytes(bytes, platform) {
  if (!bytes || bytes <= 0) {
    if (platform === 'miniprogram') return '小程序/H5暂不统计'
    return '--'
  }
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

// ─── 以下工具函数自 report/index.jsx 迁入（老长 Markdown 报告页下线后保留） ───

export function extractDatasetName(sample) {
  if (!sample) return 'Unknown'
  if (sample.top_category) return sample.top_category
  if (sample.dataset) return sample.dataset
  const id = sample.sample_id || ''
  const stripped = id.replace(/_(android|ios|miniprogram|harmony)$/, '')
  return stripped || id || 'Unknown'
}

function meanValue(arr, key) {
  const valid = arr.filter(x => x[key] !== undefined && x[key] !== null)
  if (valid.length === 0) return 0
  return valid.reduce((sum, x) => sum + x[key], 0) / valid.length
}

function sumValue(arr, key) {
  return arr.reduce((acc, x) => acc + (x[key] || 0), 0)
}

export function recalculateSummary(filteredResults) {
  if (!filteredResults || filteredResults.length === 0) {
    return {
      sample_count: 0,
      mean_success_rate: 0,
      mean_quality: 0,
      mean_experience: 0,
      per_platform: {},
    }
  }

  // 按平台分组
  const byPlatform = {}
  filteredResults.forEach(s => {
    const p = s.platform || 'unknown'
    if (!byPlatform[p]) byPlatform[p] = []
    byPlatform[p].push(s)
  })

  // 计算 E2E 统计（防御：e2e_test_cases 字段可能不是数组；tc.status 可能缺失）
  const calcE2E = (samples) => {
    let pass = 0
    let total = 0
    samples.forEach(s => {
      const cases = Array.isArray(s.e2e_test_cases) ? s.e2e_test_cases : []
      cases.forEach(tc => {
        if (tc && tc.status !== undefined) {
          total++
          if (tc.status === 'PASS') pass++
        }
      })
    })
    return { pass, total, rate: total > 0 ? (pass / total) * 100 : 0 }
  }

  // 构建 per_platform
  const perPlatform = {}
  Object.entries(byPlatform).forEach(([platform, samples]) => {
    const e2e = calcE2E(samples)
    perPlatform[platform] = {
      sample_count: samples.length,
      mean_success_rate: meanValue(samples, 'success_rate_score'),
      mean_quality: meanValue(samples, 'quality_score'),
      mean_experience: meanValue(samples, 'experience_score'),
      mean_duration_ms: meanValue(samples, 'duration_ms'),
      mean_initial_generation_rate: meanValue(samples, 'success_rate_score'),
      mean_functionality_completeness: meanValue(samples, 'functionality_score'),
      mean_stability_score: meanValue(samples, 'stability_score'),
      mean_aesthetics_score: meanValue(samples, 'aesthetics_score'),
      e2e_pass_rate: e2e.rate,
      e2e_pass: e2e.pass,
      e2e_count: e2e.total,
      total_crashes: sumValue(samples, 'crash_count'),
      total_anrs: sumValue(samples, 'anr_count'),
      total_white_screens: sumValue(samples, 'white_screen_count'),
      mean_token_total: meanValue(samples, 'token_total'),
      mean_token_input: meanValue(samples, 'token_input'),
      mean_token_output: meanValue(samples, 'token_output'),
      mean_backend_completeness: (() => {
        const valid = samples.filter(s => s.backend_completeness !== undefined && s.backend_completeness !== null)
        if (valid.length === 0) return null
        return valid.reduce((sum, s) => sum + s.backend_completeness, 0) / valid.length
      })(),
      mean_cost_usd: (() => {
        const valid = samples.filter(s => s.cost_usd != null && s.cost_usd > 0)
        if (valid.length === 0) return null
        return valid.reduce((sum, s) => sum + s.cost_usd, 0) / valid.length
      })(),
    }
  })

  return {
    sample_count: filteredResults.length,
    mean_success_rate: meanValue(filteredResults, 'success_rate_score'),
    mean_quality: meanValue(filteredResults, 'quality_score'),
    mean_experience: meanValue(filteredResults, 'experience_score'),
    per_platform: perPlatform,
    mean_initial_generation_rate: meanValue(filteredResults, 'success_rate_score'),
    mean_functionality_completeness: meanValue(filteredResults, 'functionality_score'),
    mean_stability_score: meanValue(filteredResults, 'stability_score'),
    mean_duration_ms: meanValue(filteredResults, 'duration_ms'),
    mean_token_total: meanValue(filteredResults, 'token_total'),
    total_crashes: sumValue(filteredResults, 'crash_count'),
    total_anrs: sumValue(filteredResults, 'anr_count'),
    total_white_screens: sumValue(filteredResults, 'white_screen_count'),
    mean_cost_usd: (() => {
      const valid = filteredResults.filter(s => s.cost_usd != null && s.cost_usd > 0)
      if (valid.length === 0) return null
      return valid.reduce((sum, s) => sum + s.cost_usd, 0) / valid.length
    })(),
  }
}
