import React, { useState } from 'react'
import { Checkbox, Card, Typography, Button, Badge, Divider, Radio, Tooltip, Space } from 'antd'
import { FilterOutlined, DownOutlined, UpOutlined, ReloadOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import VersionSwitcher from '../../../components/VersionSwitcher'
import { getDatasetDisplayName } from '../../../utils/displayNames'

const { Text } = Typography

const PLATFORM_LABELS = {
  android: '安卓',
  ios: 'iOS',
  miniprogram: '小程序',
}

function getLabel(value, labelMap) {
  return labelMap[value] || value
}

function FilterRow({ label, options, selected, onChange, labelMap, style, showSelectAll = false }) {
  if (!options || options.length === 0) return null

  const allValues = options.map(o => o.value)
  const selectedCount = (selected || []).length
  const isAllSelected = selectedCount === allValues.length && allValues.length > 0
  const isIndeterminate = selectedCount > 0 && !isAllSelected

  const handleSelectAll = (e) => {
    if (e.target.checked) {
      onChange(allValues)
    } else {
      onChange([])
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        padding: '6px 0',
        ...style,
      }}
    >
      <div
        style={{
          minWidth: 64,
          flexShrink: 0,
          whiteSpace: 'nowrap',
          paddingTop: 4,
          fontSize: 13,
          fontWeight: 600,
          color: '#1f2937',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <span style={{
          display: 'inline-block',
          width: 4,
          height: 14,
          borderRadius: 2,
          background: '#6366f1',
          flexShrink: 0,
        }} />
        {label}
      </div>
      <div style={{ flex: 1, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '4px 4px' }}>
        {showSelectAll && (
          <>
            <Checkbox
              checked={isAllSelected}
              indeterminate={isIndeterminate}
              onChange={handleSelectAll}
              style={{
                margin: 0,
                padding: '2px 10px',
                borderRadius: 6,
                background: isAllSelected || isIndeterminate ? '#eef2ff' : '#f5f5f5',
                color: isAllSelected || isIndeterminate ? '#4f46e5' : '#595959',
                fontWeight: 500,
              }}
            >
              {isAllSelected ? '取消全部' : '全选'}
            </Checkbox>
            <Divider type="vertical" style={{ margin: '0 4px', height: 18, borderColor: '#e5e7eb' }} />
          </>
        )}
        <Checkbox.Group
          value={selected}
          onChange={onChange}
          style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 4px', alignItems: 'center' }}
        >
          {options.map(opt => {
            const isChecked = (selected || []).includes(opt.value)
            return (
              <Checkbox
                key={opt.value}
                value={opt.value}
                style={{
                  margin: 0,
                  padding: '2px 10px',
                  borderRadius: 6,
                  background: isChecked ? '#eef2ff' : 'transparent',
                  transition: 'background 0.2s',
                }}
              >
                {labelMap ? getLabel(opt.value, labelMap) : opt.label}
              </Checkbox>
            )
          })}
        </Checkbox.Group>
      </div>
    </div>
  )
}

export default function FilterBar({
  platforms, selectedPlatforms, onPlatformChange,
  datasets, selectedDatasets, onDatasetChange,
  samples, selectedSamples, onSampleChange,
  sampleTitleMap = {},
  backendFilter, onBackendFilterChange,
  stabilityFilter, onStabilityFilterChange,
  scoreFilter, onScoreFilterChange,
  versions, selectedVersion, onVersionChange,
  onReset,
}) {
  const [expanded, setExpanded] = useState(false)

  const hasAdvanced = (datasets && datasets.length > 0) || (samples && samples.length > 0)
  // 是否存在"非全选"的高级筛选条件（用于 Badge 提示）
  const datasetFiltered = datasets && datasets.length > 0 && selectedDatasets && selectedDatasets.length !== datasets.length
  const sampleFiltered = samples && samples.length > 0 && selectedSamples && selectedSamples.length !== samples.length
  const backendActive = backendFilter && backendFilter !== 'all'
  const stabilityActive = stabilityFilter && stabilityFilter.length > 0 && stabilityFilter.length < 3
  const scoreActive = scoreFilter && scoreFilter !== 'all'
  const versionFiltered = selectedVersion && selectedVersion !== 'V2'
  const advancedActive = versionFiltered || datasetFiltered || sampleFiltered || backendActive || stabilityActive || scoreActive

  return (
    <Card
      size="small"
      style={{
        marginBottom: 16,
        borderRadius: 10,
        border: '1px solid #e5e7eb',
        background: 'linear-gradient(180deg, #fafbff 0%, #ffffff 100%)',
      }}
      bodyStyle={{ padding: '8px 12px' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <Text style={{ fontSize: 13, color: '#6b7280', fontWeight: 500 }}>
          <FilterOutlined style={{ marginRight: 6 }} />筛选
        </Text>
        <Space size={6}>
          {advancedActive && onReset && (
            <Tooltip title="重置所有筛选条件为默认值">
              <Button
                size="small"
                icon={<ReloadOutlined />}
                onClick={() => onReset && onReset()}
                style={{ borderRadius: 6 }}
              >
                重置
              </Button>
            </Tooltip>
          )}
          {hasAdvanced && (
            <Badge dot={advancedActive} offset={[-4, 4]}>
              <Button
                size="small"
                type={expanded ? 'primary' : 'default'}
                ghost={expanded}
                icon={expanded ? <UpOutlined /> : <DownOutlined />}
                onClick={() => setExpanded(v => !v)}
                style={{ borderRadius: 6 }}
              >
                高级筛选
              </Button>
            </Badge>
          )}
        </Space>
      </div>
      {versions && versions.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <VersionSwitcher
            value={selectedVersion}
            onChange={onVersionChange}
            versions={versions}
          />
        </div>
      )}
      <div style={{ background: '#f8f9fc', borderRadius: 8, padding: '4px 10px', marginBottom: 4, border: '1px solid #eef0f4' }}>
        <FilterRow
          label="平台"
          options={platforms.map(p => ({ label: p, value: p }))}
          selected={selectedPlatforms}
          onChange={onPlatformChange}
          labelMap={PLATFORM_LABELS}
        />
      </div>
      {expanded && (
        <>
          <div style={{ background: '#f8f9fc', borderRadius: 8, padding: '4px 10px', marginBottom: 4, border: '1px solid #eef0f4' }}>
            <FilterRow
              label="样本集"
              options={datasets.map(d => (
                // 兼容两种入参：{ value, label }（报告页真实样本集分组）/ 纯字符串（对比页）；
                // 展示中文名，value 保留原始标识用于筛选逻辑
                typeof d === 'string'
                  ? { label: getDatasetDisplayName(d), value: d }
                  : { label: d.label || getDatasetDisplayName(d.value), value: d.value }
              ))}
              selected={selectedDatasets}
              onChange={onDatasetChange}
              showSelectAll
            />
          </div>
          <div style={{ background: '#f8f9fc', borderRadius: 8, padding: '6px 10px', marginBottom: 4, border: '1px solid #eef0f4', display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ minWidth: 64, flexShrink: 0, fontSize: 13, fontWeight: 600, color: '#1f2937', display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ display: 'inline-block', width: 4, height: 14, borderRadius: 2, background: '#6366f1', flexShrink: 0 }} />
              后端需求
              <Tooltip title="按样本是否需要后端服务进行单选筛选">
                <QuestionCircleOutlined style={{ color: '#9ca3af', fontSize: 12 }} />
              </Tooltip>
            </div>
            <Radio.Group
              size="small"
              value={backendFilter || 'all'}
              onChange={(e) => onBackendFilterChange && onBackendFilterChange(e.target.value)}
              optionType="button"
              buttonStyle="solid"
              options={[
                { label: '全部', value: 'all' },
                { label: '需后端', value: 'requires' },
                { label: '纯前端', value: 'frontend_only' },
              ]}
            />
          </div>
          <div style={{ background: '#f8f9fc', borderRadius: 8, padding: '4px 10px', marginBottom: 4, border: '1px solid #eef0f4' }}>
            <FilterRow
              label={(
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  运行稳定性
                  <Tooltip title={(
                    <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                      <div>· 崩溃：应用进程异常退出</div>
                      <div>· 白屏：启动后界面长时间空白</div>
                      <div>· ANR：主线程卡顿无响应</div>
                      <div style={{ marginTop: 4, color: '#cbd5e1' }}>勾选后仅展示包含所选异常的样本；全选则不过滤稳定性</div>
                    </div>
                  )}>
                    <QuestionCircleOutlined style={{ color: '#9ca3af', fontSize: 12 }} />
                  </Tooltip>
                </span>
              )}
              options={[
                { label: '崩溃', value: 'crash' },
                { label: '白屏', value: 'white_screen' },
                { label: 'ANR', value: 'anr' },
              ]}
              selected={stabilityFilter || ['crash', 'white_screen', 'anr']}
              onChange={(vals) => {
                onStabilityFilterChange && onStabilityFilterChange(vals)
              }}
              showSelectAll
            />
          </div>
          <div style={{ background: '#f8f9fc', borderRadius: 8, padding: '6px 10px', marginBottom: 4, border: '1px solid #eef0f4', display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ minWidth: 64, flexShrink: 0, fontSize: 13, fontWeight: 600, color: '#1f2937', display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ display: 'inline-block', width: 4, height: 14, borderRadius: 2, background: '#6366f1', flexShrink: 0 }} />
              分数筛选
              <Tooltip title="按样本成功率分数进行筛选">
                <QuestionCircleOutlined style={{ color: '#9ca3af', fontSize: 12 }} />
              </Tooltip>
            </div>
            <Radio.Group
              size="small"
              value={scoreFilter || 'all'}
              onChange={(e) => onScoreFilterChange && onScoreFilterChange(e.target.value)}
              optionType="button"
              buttonStyle="solid"
              options={[
                { label: '全部', value: 'all' },
                { label: '低分样本（功能完整性分低于平均）', value: 'low_score' },
                { label: '失败样本（功能完整性分为0）', value: 'failed' },
              ]}
            />
          </div>
          <div style={{ background: '#f8f9fc', borderRadius: 8, padding: '4px 10px', marginBottom: 4, border: '1px solid #eef0f4' }}>
            <FilterRow
              label="样本"
              options={samples.map(s => ({ label: s, value: s }))}
              selected={selectedSamples}
              onChange={onSampleChange}
              labelMap={sampleTitleMap}
              showSelectAll
            />
          </div>
        </>
      )}
    </Card>
  )
}
