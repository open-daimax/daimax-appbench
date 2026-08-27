import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { Result, Tooltip, Space, Tabs } from 'antd'
import { FileTextOutlined, HistoryOutlined, SwapOutlined } from '@ant-design/icons'
import { getReportData, getDatasetCategories } from '../../data/local'
import { getDatasetDisplayName } from '../../utils/displayNames'
import MetaSection from './components/MetaSection'
import ScoreCards from './components/ScoreCards'
import PlatformTable from './components/PlatformTable'
import SampleTable from './components/SampleTable'
import FunctionalityModal from './components/FunctionalityModal'
import StabilityModal from './components/StabilityModal'
import FilterBar from './components/FilterBar'
import CommandHistory from './components/CommandHistory'
import ExecutionOverview from './ExecutionOverview'
import CrossPlatformReport from './CrossPlatformReport'
import { extractDatasetName, recalculateSummary } from './utils'
import './report.css'

// extractDatasetName/recalculateSummary 已迁移至 ./utils（含 cost_usd 口径），此处统一导入避免双份实现
function ReportView() {
  const { wsId } = useParams()

  const [searchParams, setSearchParams] = useSearchParams()
  const initialPlatformParam = useRef(searchParams.get('platform'))
  // 报告数据在页面加载时已随模版注入，无异步加载过程
  const reportData = React.useMemo(() => getReportData(), [])
  const error = reportData ? null : '报告数据未注入（window.__REPORT_DATA__ 缺失）'
  const [wsName, setWsName] = useState('')

  // Functionality modal state
  const [funcModalVisible, setFuncModalVisible] = useState(false)
  const [funcModalRecord, setFuncModalRecord] = useState(null)

  // Stability modal state
  const [stabModalVisible, setStabModalVisible] = useState(false)
  const [stabModalRecord, setStabModalRecord] = useState(null)

  // Filter state
  const [selectedPlatforms, setSelectedPlatforms] = useState([])
  const [selectedDatasets, setSelectedDatasets] = useState([])
  const [selectedSamples, setSelectedSamples] = useState([])
  const [backendFilter, setBackendFilter] = useState('all')
  const [stabilityFilter, setStabilityFilter] = useState(['crash', 'white_screen', 'anr'])
  const [scoreFilter, setScoreFilter] = useState('all')
  const [selectedVersion, setSelectedVersion] = useState('V2')
  // 'all' = 全部, 'low_score' = 低分样本, 'failed' = 失败样本

  // 真实样本集类别（生成时从本地 dataset/ 注入）：高级筛选“样本集”按集合分组并展示中文名
  const datasetCategories = React.useMemo(() => getDatasetCategories(), [])

  // Extract readable workspace name from wsId
  useEffect(() => {
    if (wsId) {
      const parts = wsId.split('_')
      const generator = parts[0] || ''
      const date = parts.length > 2 ? parts[parts.length - 2] : ''
      const time = parts.length > 2 ? parts[parts.length - 1] : ''
      // 通用展示：对生成器标识做首字母大写，不针对具体生成器做硬编码映射
      let name = generator ? generator.charAt(0).toUpperCase() + generator.slice(1) : ''
      if (date && date.length === 8) {
        name += ` (${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}`
        if (time && time.length === 6) {
          name += ` ${time.slice(0, 2)}:${time.slice(2, 4)}:${time.slice(4, 6)}`
        }
        name += ')'
      }
      setWsName(name || wsId)
    }
  }, [wsId])

  // Initialize filter options when report data loads
  // 防御性过滤：避免空字符串落入候选列表导致 .includes('') 误命中所有样本
  // useMemo 包裹条件初始化，保证引用稳定，避免下游 useMemo 依赖每次渲染都变化
  const sampleResults = React.useMemo(
    () => (Array.isArray(reportData?.sample_results) ? reportData.sample_results : []),
    [reportData]
  )
  const excludedSamples = Array.isArray(reportData?.excluded_samples) ? reportData.excluded_samples : []
  const allPlatforms = [...new Set(sampleResults.map(s => s.platform))].filter(p => typeof p === 'string' && p.trim() !== '')
  const allSamples = [...new Set(sampleResults.map(s => s.sample_id))].filter(p => typeof p === 'string' && p.trim() !== '')
  const allVersions = React.useMemo(
    () => [...new Set(sampleResults.map(s => s.dataset_version).filter(v => typeof v === 'string' && v.trim() !== ''))],
    [sampleResults]
  )

  // Build sample_id -> sample_title mapping from report data
  // 样本集清单中的 title 作为兜底：报告缺 sample_title 时仍能显示中文名（本地报告的主路径）
  const sampleTitleMap = React.useMemo(() => {
    const map = {}
    datasetCategories.forEach(cat => {
      (cat.samples || []).forEach(x => {
        if (x.sample_id && x.title && x.title !== x.sample_id) {
          map[x.sample_id] = x.title
        }
      })
    })
    sampleResults.forEach(s => {
      if (s.sample_id && s.sample_title) {
        map[s.sample_id] = s.sample_title
      }
    })
    return map
  }, [sampleResults, datasetCategories])

  // 样本集分组：优先按真实样本集（/api/datasets 类别及其样本清单）归组，展示中文 name；
  // 未归属任何类别的样本回退到 extractDatasetName 派生分组，保证不丢样本
  const datasetGrouping = React.useMemo(() => {
    const catEntries = datasetCategories
      .map(cat => ({
        key: `${cat.dataset_version || ''}/${cat.id}`,
        label: cat.name || getDatasetDisplayName(cat.id),
        version: String(cat.dataset_version || '').toLowerCase(),
        sampleIds: new Set((cat.samples || []).map(x => x.sample_id).filter(Boolean)),
      }))
      .filter(c => c.sampleIds.size > 0)

    const groups = new Map() // 分组 key -> { label, sampleIds:Set }
    const sampleToKeys = {}  // sample_id -> [分组 key]
    const addToGroup = (key, label, sampleId) => {
      if (!groups.has(key)) groups.set(key, { label, sampleIds: new Set() })
      groups.get(key).sampleIds.add(sampleId)
      if (!sampleToKeys[sampleId]) sampleToKeys[sampleId] = []
      if (!sampleToKeys[sampleId].includes(key)) sampleToKeys[sampleId].push(key)
    }

    sampleResults.forEach(s => {
      if (!s.sample_id) return
      let matched = catEntries.filter(c => c.sampleIds.has(s.sample_id))
      // 同一 sample_id 可能同时存在于多个版本（如 V1/games 与 V2/games），优先取同版本类别
      if (matched.length > 1 && s.dataset_version) {
        const sameVersion = matched.filter(c => c.version === String(s.dataset_version).toLowerCase())
        if (sameVersion.length > 0) matched = sameVersion
      }
      if (matched.length > 0) {
        matched.forEach(c => addToGroup(c.key, c.label, s.sample_id))
      } else {
        const fallback = extractDatasetName(s)
        addToGroup(fallback, getDatasetDisplayName(fallback), s.sample_id)
      }
    })

    const options = [...groups.entries()].map(([value, g]) => ({ value, label: g.label || value }))
    const toSamples = {}
    groups.forEach((g, key) => { toSamples[key] = g.sampleIds })
    return { options, toSamples, sampleToKeys }
  }, [sampleResults, datasetCategories])

  const allDatasets = datasetGrouping.options.map(o => o.value)
  const datasetToSamples = datasetGrouping.toSamples

  // 样本是否属于所选样本集分组（替代旧的 extractDatasetName 直接比较）
  const sampleInDatasets = useCallback((s, datasetKeys) => {
    const keys = datasetGrouping.sampleToKeys[s.sample_id] || []
    return keys.some(k => datasetKeys.includes(k))
  }, [datasetGrouping])

  // 拾取一个对 reportData 实体变化敏感的 key（优先 run_id，其次 wsId）
  // 只以“长度”作为依赖会造成：不同报告但样本数相同时不重置筛选。
  const reportResetKey = reportData?.meta?.run_id || `${wsId}_${sampleResults.length}`

  useEffect(() => {
    if (sampleResults.length > 0) {
      // 优先从 URL ?platform= 参数初始化平台筛选
      const urlPlatformStr = initialPlatformParam.current
      let defaultPlatforms
      if (urlPlatformStr) {
        const urlPlatforms = urlPlatformStr.split(',').filter(p => allPlatforms.includes(p))
        defaultPlatforms = urlPlatforms.length > 0 ? urlPlatforms : allPlatforms
        // 用完即清，后续 reportResetKey 变化按正常默认逻辑
        initialPlatformParam.current = null
      } else {
        defaultPlatforms = allPlatforms.includes('miniprogram') ? ['miniprogram'] : allPlatforms
      }
      setSelectedPlatforms(defaultPlatforms)
      setSelectedDatasets(allDatasets)
      setSelectedSamples(allSamples)
      setBackendFilter('all')
      setStabilityFilter(['crash', 'white_screen', 'anr'])
      setScoreFilter('all')
      setSelectedVersion('V2')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportResetKey])

  // 样本集分组结构变化（/api/datasets 异步返回）时重置为全选，避免选中项残留旧分组 key
  const datasetGroupingKey = allDatasets.join('|')
  useEffect(() => {
    setSelectedDatasets(allDatasets)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetGroupingKey])

  // 平台筛选变化时同步到 URL 参数
  useEffect(() => {
    if (allPlatforms.length === 0) return
    const params = new URLSearchParams(searchParams)
    // 如果选中全部平台则移除参数，保持 URL 简洁
    const isAllSelected = allPlatforms.length > 0 && selectedPlatforms.length === allPlatforms.length
    if (isAllSelected || selectedPlatforms.length === 0) {
      params.delete('platform')
    } else {
      params.set('platform', selectedPlatforms.join(','))
    }
    setSearchParams(params, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPlatforms])

  // 重置筛选到默认值
  const handleResetFilters = () => {
    const defaultPlatforms = allPlatforms.includes('miniprogram') ? ['miniprogram'] : allPlatforms
    setSelectedPlatforms(defaultPlatforms)
    setSelectedDatasets(allDatasets)
    setSelectedSamples(allSamples)
    setBackendFilter('all')
    setStabilityFilter(['crash', 'white_screen', 'anr'])
    setScoreFilter('all')
    setSelectedVersion('V2')
  }

  // Backend filter change：切换后端需求筛选时，动态更新样本勾选状态
  const handleBackendFilterChange = (value) => {
    setBackendFilter(value)
    // 根据新的 backendFilter 值，从当前选中的平台和样本集对应的样本中筛选出符合条件的样本
    const candidateSamples = sampleResults.filter(s =>
      selectedPlatforms.includes(s.platform) &&
      sampleInDatasets(s, selectedDatasets)
    )
    let matchedSampleIds
    if (value === 'requires') {
      matchedSampleIds = candidateSamples.filter(s => s.requires_backend === true).map(s => s.sample_id)
    } else if (value === 'frontend_only') {
      matchedSampleIds = candidateSamples.filter(s => !s.requires_backend).map(s => s.sample_id)
    } else {
      // 'all' - 选中所有候选样本
      matchedSampleIds = candidateSamples.map(s => s.sample_id)
    }
    setSelectedSamples([...new Set(matchedSampleIds)])
  }
  
  // Score filter change：联动更新 selectedSamples，空结果保护
  const handleScoreFilterChange = (value) => {
    setScoreFilter(value)
    const candidateSamples = sampleResults.filter(s =>
      selectedPlatforms.includes(s.platform) &&
      sampleInDatasets(s, selectedDatasets)
    )
    if (value === 'low_score') {
      const scores = candidateSamples.map(s => s.quality_score || 0)
      const avg = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : 0
      const matchedIds = candidateSamples.filter(s => (s.quality_score || 0) < avg).map(s => s.sample_id)
      if (matchedIds.length > 0) {
        setSelectedSamples([...new Set(matchedIds)])
      }
      // 如果无匹配（所有样本分数相同），不修改 selectedSamples，保持当前选择
    } else if (value === 'failed') {
      const matchedIds = candidateSamples.filter(s => (s.quality_score || 0) === 0).map(s => s.sample_id)
      if (matchedIds.length > 0) {
        setSelectedSamples([...new Set(matchedIds)])
      }
      // 如果无匹配（没有失败样本），不修改 selectedSamples，保持当前选择
    } else {
      // 'all' - 恢复全部样本
      const allIds = candidateSamples.map(s => s.sample_id)
      setSelectedSamples([...new Set(allIds)])
    }
  }

  // Stability filter change：切换运行稳定性筛选时，动态更新样本勾选状态
  const handleStabilityFilterChange = (values) => {
    setStabilityFilter(values)
    // 根据新的 stabilityFilter 值，从当前选中的平台和样本集对应的样本中筛选出符合条件的样本
    const candidateSamples = sampleResults.filter(s =>
      selectedPlatforms.includes(s.platform) &&
      sampleInDatasets(s, selectedDatasets)
    )
    let matchedSampleIds
    if (!values || values.length === 0 || values.length === 3) {
      // 全选或全不选 → 选中所有候选样本
      matchedSampleIds = candidateSamples.map(s => s.sample_id)
    } else {
      // 部分选中：只勾选有对应问题的样本
      matchedSampleIds = candidateSamples.filter(s => {
        return values.some(type => {
          if (type === 'crash') return (s.crash_count || 0) > 0
          if (type === 'white_screen') return (s.white_screen_count || 0) > 0
          if (type === 'anr') return (s.anr_count || 0) > 0
          return false
        })
      }).map(s => s.sample_id)
    }
    setSelectedSamples([...new Set(matchedSampleIds)])
  }

  // Cascading: when dataset changes, update samples accordingly
  const handleDatasetChange = (newDatasets) => {
    const removed = selectedDatasets.filter(d => !newDatasets.includes(d))
    const added = newDatasets.filter(d => !selectedDatasets.includes(d))
    setSelectedDatasets(newDatasets)

    let newSamples = [...selectedSamples]
    // Remove samples belonging to deselected datasets
    removed.forEach(ds => {
      const samplesInDs = datasetToSamples[ds] || new Set()
      newSamples = newSamples.filter(s => !samplesInDs.has(s))
    })
    // Add samples belonging to newly selected datasets
    added.forEach(ds => {
      const samplesInDs = datasetToSamples[ds] || new Set()
      samplesInDs.forEach(s => {
        if (!newSamples.includes(s)) newSamples.push(s)
      })
    })
    setSelectedSamples(newSamples)
  }

  // Filtered results (用 useMemo 缓存，避免筛选状态未变时重复计算)
  const filteredResults = React.useMemo(() => {
    return sampleResults
      .filter(s =>
        selectedPlatforms.includes(s.platform) &&
        sampleInDatasets(s, selectedDatasets) &&
        selectedSamples.includes(s.sample_id) &&
        (allVersions.length === 0 || !selectedVersion || s.dataset_version === selectedVersion)
      )
      .filter(s => {
        if (backendFilter === 'requires') return s.requires_backend === true
        if (backendFilter === 'frontend_only') return !s.requires_backend
        return true
      })
      .filter(s => {
        if (!stabilityFilter || stabilityFilter.length === 0 || stabilityFilter.length === 3) return true
        return stabilityFilter.some(type => {
          if (type === 'crash') return (s.crash_count || 0) > 0
          if (type === 'white_screen') return (s.white_screen_count || 0) > 0
          if (type === 'anr') return (s.anr_count || 0) > 0
          return false
        })
      })
  }, [sampleResults, selectedPlatforms, selectedDatasets, selectedSamples, backendFilter, stabilityFilter, selectedVersion, sampleInDatasets, allVersions])

  const filteredSummary = React.useMemo(
    () => recalculateSummary(filteredResults),
    [filteredResults]
  )

  const handleShowFunctionality = (record) => {
    setFuncModalRecord(record)
    setFuncModalVisible(true)
  }

  const handleShowStability = (record) => {
    setStabModalRecord(record)
    setStabModalVisible(true)
  }

  // 用例纠正需后端写接口，本地报告不提供；reportData 仅在初始注入时赋值

  if (error) {
    return (
      <div style={{
        height: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#F8FAFC'
      }}>
        <Result
          status="error"
          title="报告加载失败"
          subTitle={error}
        />
      </div>
    )
  }

  const meta = reportData?.meta
  const totalSampleCount = sampleResults.length + excludedSamples.length

  // 判断是否为多端报告
  const isMultiPlatform = Array.isArray(reportData?.meta?.platform) && reportData.meta.platform.length > 1

  const tabItems = [
    ...(isMultiPlatform ? [{
      key: 'cross-platform',
      label: (
        <span>
          <SwapOutlined style={{ marginRight: 6 }} />
          多端对比
        </span>
      ),
      children: (
        <CrossPlatformReport reportData={reportData} selectedPlatforms={selectedPlatforms} />
      ),
    }] : []),
    {
      key: 'report',
      label: (
        <span>
          <FileTextOutlined style={{ marginRight: 6 }} />
          报告
        </span>
      ),
      children: (
        <>
          {/* Meta Section */}
          {meta && (
            <div className="report-section">
              <MetaSection meta={meta} totalSampleCount={totalSampleCount} excludedCount={excludedSamples.length} />
            </div>
          )}

          {/* Filter Bar */}
          {sampleResults.length > 0 && (
            <div className="report-section">
              <FilterBar
                platforms={allPlatforms}
                selectedPlatforms={selectedPlatforms}
                onPlatformChange={setSelectedPlatforms}
                datasets={datasetGrouping.options}
                selectedDatasets={selectedDatasets}
                onDatasetChange={handleDatasetChange}
                samples={allSamples}
                selectedSamples={selectedSamples}
                onSampleChange={setSelectedSamples}
                sampleTitleMap={sampleTitleMap}
                backendFilter={backendFilter}
                onBackendFilterChange={handleBackendFilterChange}
                stabilityFilter={stabilityFilter}
                onStabilityFilterChange={handleStabilityFilterChange}
                scoreFilter={scoreFilter}
                onScoreFilterChange={handleScoreFilterChange}
                versions={allVersions}
                selectedVersion={selectedVersion}
                onVersionChange={setSelectedVersion}
                onReset={handleResetFilters}
              />
            </div>
          )}

          {/* Score Cards */}
          {filteredSummary && (
            <ScoreCards summary={filteredSummary} />
          )}

          {/* Platform Table */}
          {filteredSummary?.per_platform && Object.keys(filteredSummary.per_platform).length > 0 && (
            <div className="report-section">
              <div className="report-section-title">分平台指标</div>
              <PlatformTable perPlatform={filteredSummary.per_platform} />
            </div>
          )}

          {/* Execution Overview */}
          {reportData?.execution_overview && (
            <div className="report-section">
              <div className="report-section-title">执行总览</div>
              <ExecutionOverview executionOverview={reportData.execution_overview} sampleTitleMap={sampleTitleMap} />
            </div>
          )}

          {/* Sample Table */}
          {(filteredResults.length > 0 || excludedSamples.length > 0) && (
            <div className="report-section">
              <SampleTable
                sampleResults={filteredResults}
                excludedSamples={excludedSamples}
                sampleTitleMap={sampleTitleMap}
                onShowFunctionality={handleShowFunctionality}
                onShowStability={handleShowStability}
              />
            </div>
          )}
        </>
      )
    },
    {
      key: 'history',
      label: (
        <span>
          <HistoryOutlined style={{ marginRight: 6 }} />
          操作历史
        </span>
      ),
      children: (
        <div className="report-section">
          <CommandHistory />
        </div>
      )
    }
  ]

  return (
    <div className="report-page">
      {/* Toolbar */}
      <div className="report-toolbar">
        <Space style={{ flex: 1, overflow: 'hidden' }}>
          <span className="report-toolbar-icon"><FileTextOutlined /></span>
          <div style={{ minWidth: 0, overflow: 'hidden' }}>
            <Tooltip title={wsId}>
              <div className="report-toolbar-title">{wsName || wsId}</div>
            </Tooltip>
            {wsName && wsName !== wsId && (
              <div className="report-toolbar-sub">{wsId}</div>
            )}
          </div>
        </Space>
      </div>

      <Tabs defaultActiveKey="report" items={tabItems} />

      {/* Modals */}
      <FunctionalityModal
        visible={funcModalVisible}
        onClose={() => setFuncModalVisible(false)}
        record={funcModalRecord}
        selectedPlatforms={selectedPlatforms}
      />
      <StabilityModal
        visible={stabModalVisible}
        onClose={() => setStabModalVisible(false)}
        record={stabModalRecord}
      />
    </div>
  )
}

export default ReportView
