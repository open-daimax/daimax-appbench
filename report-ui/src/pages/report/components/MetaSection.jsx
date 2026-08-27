import React from 'react'
import { Tag } from 'antd'
import dayjs from 'dayjs'

// 平台标签配色，与仪表盘保持一致的色彩语义
const PLATFORM_COLORS = { ios: 'blue', android: 'green', miniprogram: 'orange', h5: 'cyan' }

export default function MetaSection({ meta, totalSampleCount, excludedCount }) {
  if (!meta) return null

  // 容错处理：platform 字段
  const platformStr = (() => {
    if (meta.platform && typeof meta.platform === 'string') return meta.platform
    if (meta.platforms && Array.isArray(meta.platforms)) return meta.platforms.join(',')
    return ''
  })()
  const platforms = platformStr.split(',').map(p => p.trim()).filter(Boolean)

  // 容错处理：run_id 回退从 workspace 名解析
  const runId = meta.run_id || meta.workspace_name || '-'

  // 样本数显示：优先使用传入的总数，回退到 meta.sample_count
  const sampleCountDisplay = (() => {
    if (typeof totalSampleCount === 'number') {
      return totalSampleCount.toString()
    }
    return String(meta.sample_count ?? '-')
  })()

  const fmtTime = (t) => (t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-')

  // 与旧版 Descriptions 字段一一对应，仅换为现代网格布局
  const items = [
    { label: 'Run ID', value: runId, mono: true },
    { label: 'Generator', value: meta.generator || '-' },
    { label: '工作区名称', value: meta.workspace_name || '-', mono: true },
    { label: '生成器分支', value: meta.generator_branch || '-', mono: true },
    {
      label: 'Platform',
      render: platforms.length > 0
        ? platforms.map(p => (
          <Tag key={p} color={PLATFORM_COLORS[p] || 'blue'} style={{ marginRight: 4 }}>{p}</Tag>
        ))
        : '-',
    },
    { label: '开始时间', value: fmtTime(meta.start_time) },
    { label: '结束时间', value: fmtTime(meta.end_time) },
    { label: '评测版本', value: meta.eval_version || '-' },
    {
      label: '样本数',
      render: (
        <>
          {sampleCountDisplay}
          {excludedCount > 0 && (
            <span style={{ fontSize: 12, color: '#94A3B8', fontWeight: 400, marginLeft: 6 }}>
              （含 {excludedCount} 个已排除）
            </span>
          )}
        </>
      ),
    },
  ]

  return (
    <div>
      <div className="report-section-title">评测元信息</div>
      <div className="report-meta-grid">
        {items.map(item => (
          <div key={item.label}>
            <div className="report-meta-label">{item.label}</div>
            <div className={`report-meta-value${item.mono ? ' report-meta-value--mono' : ''}`}>
              {item.render ?? item.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
