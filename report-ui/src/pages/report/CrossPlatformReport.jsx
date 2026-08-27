import React, { useState, useMemo } from 'react'
import {
  Card, Row, Col, Table, Collapse, Modal,
  Tag, Typography, Space, Empty, Image, Spin,
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined,
  SwapOutlined, ThunderboltOutlined, StarOutlined,
  SmileOutlined, DesktopOutlined, BugOutlined,
  EyeOutlined, SafetyCertificateOutlined, PictureOutlined,
} from '@ant-design/icons'
import LazyImage from './components/LazyImage'
import { formatDuration } from './utils'
import { getSampleScreenshots, getScreenshotUrl } from '../../data/local'

const { Title, Text } = Typography

/* ====================================================================
 * 辅助函数
 * ==================================================================== */

// 格式化包大小
const formatSize = (bytes) => {
  if (!bytes) return '--'
  if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}MB`
  return `${(bytes / 1024).toFixed(1)}KB`
}

// 平台显示名映射
const PLATFORM_LABELS = {
  expo_ios: 'iOS',
  expo_android: 'Android',
  expo_web: 'Web',
  miniprogram: '小程序',
  ios: 'iOS',
  android: 'Android',
}

// 平台颜色映射
const PLATFORM_COLORS = {
  expo_ios: '#007AFF',
  expo_android: '#3DDC84',
  expo_web: '#6366f1',
  miniprogram: '#07c160',
  ios: '#007AFF',
  android: '#3DDC84',
}

// 按 sample_id 分组 sample_results
const groupBySample = (results) => {
  return results.reduce((acc, item) => {
    if (!acc[item.sample_id]) acc[item.sample_id] = []
    acc[item.sample_id].push(item)
    return acc
  }, {})
}

// 安全格式化数字
const safeFormat = (v, suffix = '', decimals = 1) => {
  if (v === undefined || v === null) return '--'
  const n = Number(v)
  if (!Number.isFinite(n)) return '--'
  return `${n.toFixed(decimals)}${suffix}`
}

// 一致性分颜色（越高越绿，越低越红）
const consistencyColor = (score) => {
  if (score === undefined || score === null) return '#999'
  if (score >= 90) return '#52c41a'
  if (score >= 70) return '#1890ff'
  if (score >= 50) return '#faad14'
  return '#ff4d4f'
}

// 构建截图 URL（入参可能是完整路径，取文件名后到注入的截图清单里查相对路径）
const buildScreenshotUrl = (sampleId, relativePath) => {
  if (!sampleId || !relativePath) return null
  return getScreenshotUrl(sampleId, relativePath.split('/').pop())
}

/* ====================================================================
 * 子组件：用例详情弹窗（支持截图序列对比）
 * ==================================================================== */
function TestCaseDetailModal({ visible, onClose, testCase, platforms, groupedResults, sampleId }) {
  const tcId = testCase?.test_case_id || testCase?.id || ''
  const tcName = testCase?.test_case_name || testCase?.name || ''
  const details = testCase?.details || testCase?.ai_observation || ''

  // 截图清单随报告注入，同步取用，无加载态与竞态
  const screenshots = useMemo(() => (sampleId ? getSampleScreenshots(sampleId) : []), [sampleId])

  // 筛选当前用例的截图（精确匹配 + 大小写不敏感回退）
  const caseScreenshots = useMemo(() => {
    if (!tcId || !screenshots.length) return []
    let filtered = screenshots.filter(s => s.tc_id === tcId)
    if (filtered.length === 0) {
      const lowerTcId = tcId.toLowerCase()
      filtered = screenshots.filter(s => s.tc_id && s.tc_id.toLowerCase() === lowerTcId)
    }
    return filtered
  }, [tcId, screenshots])

  // 按步骤分组：step_num -> { platform: screenshot_entry }
  const stepsMap = useMemo(() => {
    const map = new Map()
    caseScreenshots.forEach(s => {
      const step = s.step || 0
      if (!map.has(step)) map.set(step, {})
      map.get(step)[s.platform] = s
    })
    return [...map.entries()].sort((a, b) => a[0] - b[0])
  }, [caseScreenshots])

  // 收集该用例在各平台的通过状态
  const platformStatus = platforms.map(p => {
    const resultsForPlatform = (groupedResults || []).filter(r => r.platform === p)
    for (const result of resultsForPlatform) {
      const cases = Array.isArray(result.e2e_test_cases) ? result.e2e_test_cases : []
      const matched = cases.find(c => (c.test_case_id || c.id) === tcId)
      if (matched) {
        return {
          platform: p,
          passed: matched.passed || matched.status === 'PASS',
          details: matched.details || matched.ai_observation || '',
        }
      }
    }
    return { platform: p, passed: null, details: '' }
  })

  // 构建截图 URL（注入清单已带 url，缺失时按文件名回退）
  const resolveScreenshotUrl = (s) => {
    if (!s) return null
    if (s.url) return s.url
    if (s.filename && sampleId) {
      return getScreenshotUrl(sampleId, s.filename)
    }
    return null
  }

  const statusColumns = [
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      render: (p) => <Tag color={PLATFORM_COLORS[p] || '#1890ff'}>{PLATFORM_LABELS[p] || p}</Tag>,
    },
    {
      title: '通过状态',
      dataIndex: 'passed',
      key: 'passed',
      render: (v) => {
        if (v === null) return <Text type="secondary">未测试</Text>
        return v
          ? <Tag color="success"><CheckCircleOutlined /> 通过</Tag>
          : <Tag color="error"><CloseCircleOutlined /> 失败</Tag>
      },
    },
    {
      title: 'AI 观察描述',
      dataIndex: 'details',
      key: 'details',
      render: (v) => v || <Text type="secondary">无</Text>,
    },
  ]

  if (!testCase) return null

  // 动态调整 Modal 宽度：根据平台数量
  const modalWidth = Math.max(900, 200 * platforms.length + 300)

  return (
    <Modal
      title={
        <Space>
          <EyeOutlined style={{ color: '#1890ff' }} />
          <span>用例详情 — {tcName}</span>
        </Space>
      }
      open={visible}
      onCancel={onClose}
      footer={null}
      width={modalWidth}
    >
      <div style={{ marginBottom: 16 }}>
        <Text strong>用例 ID：</Text><Text>{tcId}</Text>
        <br />
        <Text strong>用例名称：</Text><Text>{tcName}</Text>
        {testCase.description && (
          <>
            <br />
            <Text strong>描述：</Text><Text>{testCase.description}</Text>
          </>
        )}
      </div>
      {details && (
        <Card size="small" title="AI 观察描述" style={{ marginBottom: 16 }}>
          <pre style={{
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            fontSize: 13,
            lineHeight: 1.7,
            margin: 0,
          }}>
            {details}
          </pre>
        </Card>
      )}
      <Text strong style={{ marginBottom: 8, display: 'block' }}>各平台通过状态对比：</Text>
      <Table
        dataSource={platformStatus.map(s => ({ ...s, key: s.platform }))}
        columns={statusColumns}
        size="small"
        pagination={false}
        style={{ marginBottom: 16 }}
      />

      {/* 操作截图序列 */}
      <div style={{ marginTop: 16 }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12,
          marginBottom: 12, paddingBottom: 8,
          borderBottom: '1px solid #f0f0f0',
        }}>
          <PictureOutlined style={{ color: '#1890ff' }} />
          <Text strong style={{ fontSize: 14 }}>操作截图序列</Text>
        </div>

        {stepsMap.length === 0 && (
          <Empty
            description="暂无步骤截图"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            style={{ margin: '16px 0' }}
          />
        )}

        {stepsMap.length > 0 && (
          <Image.PreviewGroup>
            {stepsMap.map(([stepNum, platformShots]) => (
              <div key={stepNum} style={{ marginBottom: 20 }}>
                <Text type="secondary" style={{ fontSize: 13, marginBottom: 8, display: 'block' }}>
                  Step {stepNum}
                </Text>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                  {platforms.map(p => {
                    const shot = platformShots[p]
                    const url = resolveScreenshotUrl(shot)
                    return (
                      <div key={p} style={{ textAlign: 'center' }}>
                        <Tag color={PLATFORM_COLORS[p] || '#1890ff'} style={{ marginBottom: 4 }}>
                          {PLATFORM_LABELS[p] || p}
                        </Tag>
                        {url ? (
                          <div>
                            <Image
                              src={url}
                              alt={`${PLATFORM_LABELS[p] || p} - Step ${stepNum}`}
                              width={160}
                              style={{
                                borderRadius: 4,
                                border: '1px solid #e8e8e8',
                                objectFit: 'contain',
                                background: '#fafafa',
                                maxHeight: 320,
                              }}
                              placeholder={
                                <div style={{
                                  width: 160, height: 280,
                                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                                  background: '#f5f5f5', borderRadius: 4,
                                }}>
                                  <Spin />
                                </div>
                              }
                              fallback="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='280' viewBox='0 0 160 280'%3E%3Crect fill='%23f5f5f5' width='160' height='280'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' fill='%23999' font-size='12'%3E截图加载失败%3C/text%3E%3C/svg%3E"
                            />
                          </div>
                        ) : (
                          <div style={{
                            width: 160,
                            height: 280,
                            background: '#f5f5f5',
                            border: '1px dashed #d9d9d9',
                            borderRadius: 4,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: '#bbb',
                            fontSize: 12,
                          }}>
                            {shot ? '截图缺失' : '未执行'}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </Image.PreviewGroup>
        )}
      </div>
    </Modal>
  )
}

/* ====================================================================
 * 子组件：评测详情展开区（6个步骤）
 * ==================================================================== */
function EvaluationDetailPanel({ sampleId, groupedResults, platforms }) {
  const [detailModalVisible, setDetailModalVisible] = useState(false)
  const [selectedTestCase, setSelectedTestCase] = useState(null)

  const results = groupedResults || []

  // Step 1: 代码生成
  const genStepItems = results.map(r => ({
    platform: r.platform,
    success: r.generation_success,
    duration: r.generation_duration_ms || r.duration_ms,
    tokenInput: r.token_input,
    tokenOutput: r.token_output,
    tokenTotal: r.token_total,
  }))

  // Step 2: 构建
  const buildStepItems = results.map(r => ({
    platform: r.platform,
    success: r.build_success ?? null,
    duration: r.build_duration_ms,
    packageSize: r.package_size_bytes,
  }))

  // Step 3: 安装与启动
  const installStepItems = results.map(r => ({
    platform: r.platform,
    installSuccess: r.install_success,
    launchSuccess: r.launch_success,
    screenshotPath: r.screenshots?.launch || r.screenshot_path,
  }))

  // Step 4: E2E 测试用例 — 矩阵，行=用例，列=平台
  const allTestCaseIds = useMemo(() => {
    const ids = new Map()
    results.forEach(r => {
      const cases = Array.isArray(r.e2e_test_cases) ? r.e2e_test_cases : []
      cases.forEach(tc => {
        const id = tc.test_case_id || tc.id
        if (!ids.has(id)) {
          ids.set(id, { id, name: tc.test_case_name || tc.name || id })
        }
      })
    })
    return [...ids.values()]
  }, [results])

  // Step 5: 稳定性
  const stabilityItems = results.map(r => ({
    platform: r.platform,
    crashes: r.crash_count || 0,
    anrs: r.anr_count || 0,
    whiteScreens: r.white_screen_count || 0,
  }))

  // Step 6: 美观性
  const aestheticsItems = results.map(r => ({
    platform: r.platform,
    dimensions: r.aesthetics_dimensions || {},
    score: r.aesthetics_score,
  }))
  const aestheticsDimensionNames = useMemo(() => {
    const names = new Set()
    aestheticsItems.forEach(item => {
      Object.keys(item.dimensions).forEach(k => names.add(k))
    })
    return [...names]
  }, [aestheticsItems])

  const handleTestCaseClick = (tc) => {
    setSelectedTestCase(tc)
    setDetailModalVisible(true)
  }

  // 用例矩阵：行=用例，列=平台
  const e2eMatrixData = allTestCaseIds.map(tc => {
    const row = { key: tc.id, tcId: tc.id, tcName: tc.name }
    results.forEach(r => {
      const cases = Array.isArray(r.e2e_test_cases) ? r.e2e_test_cases : []
      const matched = cases.find(c => (c.test_case_id || c.id) === tc.id)
      row[r.platform] = matched || null
    })
    return row
  })

  const e2eColumns = [
    { title: '用例 ID', dataIndex: 'tcId', key: 'tcId', width: 100 },
    { title: '用例名称', dataIndex: 'tcName', key: 'tcName', ellipsis: true },
    ...platforms.map(p => ({
      title: <Tag color={PLATFORM_COLORS[p] || '#1890ff'}>{PLATFORM_LABELS[p] || p}</Tag>,
      dataIndex: p,
      key: p,
      width: 110,
      render: (tcData) => {
        if (!tcData) return <Text type="secondary">N/A</Text>
        const passed = tcData.passed || tcData.status === 'PASS'
        if (passed) {
          return (
            <Tag
              color="success"
              style={{ cursor: 'pointer' }}
              onClick={() => handleTestCaseClick(tcData)}
            >
              <CheckCircleOutlined /> 通过
            </Tag>
          )
        }
        return (
          <Tag
            color="error"
            style={{ cursor: 'pointer' }}
            onClick={() => handleTestCaseClick(tcData)}
          >
            <CloseCircleOutlined /> 失败
          </Tag>
        )
      },
    })),
  ]

  // 美观性维度表：行=维度，列=平台
  const aestheticsTableData = aestheticsDimensionNames.map(dim => {
    const row = { key: dim, dimension: dim }
    aestheticsItems.forEach(item => {
      row[item.platform] = item.dimensions[dim] ?? null
    })
    return row
  })

  const aestheticsColumns = [
    { title: '维度', dataIndex: 'dimension', key: 'dimension' },
    ...platforms.map(p => ({
      title: <Tag color={PLATFORM_COLORS[p] || '#1890ff'}>{PLATFORM_LABELS[p] || p}</Tag>,
      dataIndex: p,
      key: p,
      render: (v) => {
        if (v === null || v === undefined) return <Text type="secondary">--</Text>
        return safeFormat(v, '/10')
      },
    })),
  ]


  return (
    <div>
      <Collapse
        size="small"
        items={[
          {
            key: 'step1',
            label: <Space><ThunderboltOutlined /> Step 1: 代码生成</Space>,
            children: (
              <Table
                dataSource={genStepItems.map(r => ({ ...r, key: r.platform }))}
                columns={[
                  { title: '平台', dataIndex: 'platform', key: 'platform', render: p => <Tag color={PLATFORM_COLORS[p] || '#1890ff'}>{PLATFORM_LABELS[p] || p}</Tag> },
                  { title: '状态', dataIndex: 'success', key: 'success', render: v => v ? <Tag color="success">成功</Tag> : (v === false ? <Tag color="error">失败</Tag> : <Text type="secondary">--</Text>) },
                  { title: '耗时', dataIndex: 'duration', key: 'duration', render: v => formatDuration(v) },
                  { title: 'Token 输入', dataIndex: 'tokenInput', key: 'tokenInput', render: v => v != null ? Math.round(v).toLocaleString('zh-CN') : '--' },
                  { title: 'Token 输出', dataIndex: 'tokenOutput', key: 'tokenOutput', render: v => v != null ? Math.round(v).toLocaleString('zh-CN') : '--' },
                  { title: 'Token 总计', dataIndex: 'tokenTotal', key: 'tokenTotal', render: v => v != null ? Math.round(v).toLocaleString('zh-CN') : '--' },
                ]}
                size="small"
                pagination={false}
              />
            ),
          },
          {
            key: 'step2',
            label: <Space><DesktopOutlined /> Step 2: 构建</Space>,
            children: (
              <Table
                dataSource={buildStepItems.map(r => ({ ...r, key: r.platform }))}
                columns={[
                  { title: '平台', dataIndex: 'platform', key: 'platform', render: p => <Tag color={PLATFORM_COLORS[p] || '#1890ff'}>{PLATFORM_LABELS[p] || p}</Tag> },
                  { title: '状态', dataIndex: 'success', key: 'success', render: v => v === true ? <Tag color="success">成功</Tag> : (v === false ? <Tag color="error">失败</Tag> : <Text type="secondary">--</Text>) },
                  { title: '耗时', dataIndex: 'duration', key: 'duration', render: v => formatDuration(v) },
                  { title: '包大小', dataIndex: 'packageSize', key: 'packageSize', render: v => formatSize(v) },
                ]}
                size="small"
                pagination={false}
              />
            ),
          },
          {
            key: 'step3',
            label: <Space><CheckCircleOutlined /> Step 3: 安装与启动</Space>,
            children: (
              <Table
                dataSource={installStepItems.map(r => ({ ...r, key: r.platform }))}
                columns={[
                  { title: '平台', dataIndex: 'platform', key: 'platform', render: p => <Tag color={PLATFORM_COLORS[p] || '#1890ff'}>{PLATFORM_LABELS[p] || p}</Tag> },
                  { title: '安装', dataIndex: 'installSuccess', key: 'installSuccess', render: v => v ? <Tag color="success">成功</Tag> : (v === false ? <Tag color="error">失败</Tag> : <Text type="secondary">--</Text>) },
                  { title: '启动', dataIndex: 'launchSuccess', key: 'launchSuccess', render: v => v ? <Tag color="success">成功</Tag> : (v === false ? <Tag color="error">失败</Tag> : <Text type="secondary">--</Text>) },
                  { title: '截图', dataIndex: 'screenshotPath', key: 'screenshot', render: (path) => {
                    if (!path) return <Text type="secondary">无</Text>
                    const url = buildScreenshotUrl(sampleId, path)
                    return url ? <a href={url} target="_blank" rel="noreferrer"><EyeOutlined /> 查看</a> : <Text type="secondary">无</Text>
                  }},
                ]}
                size="small"
                pagination={false}
              />
            ),
          },
          {
            key: 'step4',
            label: <Space><SafetyCertificateOutlined /> Step 4: E2E 测试用例</Space>,
            children: allTestCaseIds.length === 0
              ? <Text type="secondary">无测试用例数据</Text>
              : (
                <Table
                  dataSource={e2eMatrixData}
                  columns={e2eColumns}
                  size="small"
                  pagination={false}
                  scroll={{ x: 'max-content' }}
                />
              ),
          },
          {
            key: 'step5',
            label: <Space><BugOutlined /> Step 5: 稳定性分析</Space>,
            children: (
              <Table
                dataSource={stabilityItems.map(r => ({ ...r, key: r.platform }))}
                columns={[
                  { title: '平台', dataIndex: 'platform', key: 'platform', render: p => <Tag color={PLATFORM_COLORS[p] || '#1890ff'}>{PLATFORM_LABELS[p] || p}</Tag> },
                  { title: '崩溃', dataIndex: 'crashes', key: 'crashes', render: v => <Tag color={v > 0 ? 'error' : 'success'}>{v}</Tag> },
                  { title: 'ANR', dataIndex: 'anrs', key: 'anrs', render: v => <Tag color={v > 0 ? 'warning' : 'success'}>{v}</Tag> },
                  { title: '白屏', dataIndex: 'whiteScreens', key: 'whiteScreens', render: v => <Tag color={v > 0 ? 'warning' : 'success'}>{v}</Tag> },
                ]}
                size="small"
                pagination={false}
              />
            ),
          },
          {
            key: 'step6',
            label: <Space><StarOutlined /> Step 6: 美观性评估</Space>,
            children: aestheticsDimensionNames.length === 0
              ? <Text type="secondary">无美观性数据</Text>
              : (
                <Table
                  dataSource={aestheticsTableData}
                  columns={aestheticsColumns}
                  size="small"
                  pagination={false}
                  scroll={{ x: 'max-content' }}
                />
              ),
          },
        ]}
      />

      <TestCaseDetailModal
        visible={detailModalVisible}
        onClose={() => { setDetailModalVisible(false); setSelectedTestCase(null) }}
        testCase={selectedTestCase}
        platforms={platforms}
        groupedResults={results}
        sampleId={sampleId}
      />
    </div>
  )
}

/* ====================================================================
 * 主组件：CrossPlatformReport
 * ==================================================================== */
export default function CrossPlatformReport({ reportData, selectedPlatforms }) {
  const meta = reportData ? (reportData.meta || {}) : {}
  const allPlatforms = Array.isArray(meta.platform) ? meta.platform : []
  // 根据 selectedPlatforms 过滤展示的平台（为空或全选时展示全部）
  const platforms = (Array.isArray(selectedPlatforms) && selectedPlatforms.length > 0)
    ? allPlatforms.filter(p => selectedPlatforms.includes(p))
    : allPlatforms
  const crossComparison = reportData ? (reportData.cross_platform_comparison || {}) : {}
  const topSummary = reportData ? (reportData.top_level_summary || {}) : {}
  const allSampleResults = reportData && Array.isArray(reportData.sample_results) ? reportData.sample_results : []
  // 按 selectedPlatforms 过滤样本结果
  const sampleResults = (Array.isArray(selectedPlatforms) && selectedPlatforms.length > 0)
    ? allSampleResults.filter(s => selectedPlatforms.includes(s.platform))
    : allSampleResults

  // 按 sample_id 分组
  const grouped = useMemo(() => groupBySample(sampleResults), [sampleResults])

  if (!reportData) return null

  // 顶层指标卡片数据
  const overviewCards = [
    {
      title: '一致性分',
      value: topSummary.mean_consistency_score ?? 0,
      suffix: '%',
      icon: <SwapOutlined />,
      iconColor: '#52c41a',
      valueGradient: 'linear-gradient(135deg, #34d399 0%, #10b981 100%)',
    },
    {
      title: '平均成功率',
      value: topSummary.mean_success_rate ?? 0,
      suffix: '%',
      icon: <CheckCircleOutlined />,
      iconColor: '#1890ff',
      valueGradient: 'linear-gradient(135deg, #60a5fa 0%, #2563eb 100%)',
    },
    {
      title: '平均功能完整性',
      value: topSummary.mean_quality ?? 0,
      suffix: '分',
      icon: <StarOutlined />,
      iconColor: '#7c3aed',
      valueGradient: 'linear-gradient(135deg, #a78bfa 0%, #7c3aed 100%)',
    },
    {
      title: '平均体验',
      value: topSummary.mean_experience ?? 0,
      suffix: '分',
      icon: <SmileOutlined />,
      iconColor: '#f59e0b',
      valueGradient: 'linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%)',
    },
  ]

  // 平台对比总览表数据
  const perPlatform = topSummary.per_platform || {}
  const platformTableData = platforms.map(p => {
    const data = perPlatform[p] || {}
    return {
      key: p,
      platform: p,
      successRate: data.mean_success_rate,
      quality: data.mean_quality,
      experience: data.mean_experience,
      e2ePassRate: data.e2e_pass_rate != null ? (data.e2e_pass_rate * 100) : null,
      e2ePass: data.e2e_pass,
      e2eTotal: data.e2e_count,
      duration: data.mean_duration_ms,
      aesthetics: data.mean_aesthetics_score,
      functionality: data.mean_functionality_completeness,
      crashes: data.total_crashes ?? 0,
      anrs: data.total_anrs ?? 0,
      whiteScreens: data.total_white_screens ?? 0,
    }
  })

  const platformTableColumns = [
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      render: p => <Tag color={PLATFORM_COLORS[p] || '#1890ff'}>{PLATFORM_LABELS[p] || p}</Tag>,
    },
    {
      title: '成功率',
      dataIndex: 'successRate',
      key: 'successRate',
      render: v => safeFormat(v, '%'),
    },
    {
      title: '功能完整性均分',
      dataIndex: 'quality',
      key: 'quality',
      render: v => safeFormat(v, '分'),
    },
    {
      title: '体验均分',
      dataIndex: 'experience',
      key: 'experience',
      render: v => safeFormat(v, '分'),
    },
    {
      title: '美观度',
      dataIndex: 'aesthetics',
      key: 'aesthetics',
      render: v => safeFormat(v, '分'),
    },
    {
      title: '用例完整性',
      dataIndex: 'functionality',
      key: 'functionality',
      render: v => safeFormat(v, '%'),
    },
    {
      title: 'E2E 通过率',
      dataIndex: 'e2ePassRate',
      key: 'e2ePassRate',
      render: (v, row) => {
        if (v === null || v === undefined) return '--'
        return (
          <Space>
            <span>{safeFormat(v, '%')}</span>
            <Text type="secondary" style={{ fontSize: 12 }}>
              ({row.e2ePass ?? '--'}/{row.e2eTotal ?? '--'})
            </Text>
          </Space>
        )
      },
    },
    {
      title: '平均耗时',
      dataIndex: 'duration',
      key: 'duration',
      render: v => formatDuration(v),
    },
    {
      title: '崩溃 / 白屏',
      key: 'stability',
      render: (_, row) => (
        <Space size={4}>
          <Tag color={row.crashes > 0 ? 'error' : 'success'}>{row.crashes} 崩溃</Tag>
          <Tag color={row.whiteScreens > 0 ? 'warning' : 'success'}>{row.whiteScreens} 白屏</Tag>
        </Space>
      ),
    },
  ]

  // 样本级对比 Collapse items
  const sampleComparisonItems = Object.entries(crossComparison).map(([sampleId, compData]) => {
    const platformResults = grouped[sampleId] || []
    const sampleTitle = platformResults[0]?.sample_title || sampleId
    const consistencyScore = compData.consistency_score
    const dimComp = compData.dimension_comparison || {}
    const screenshots = compData.screenshots || {}

    // 各平台关键指标
    const metricRowData = platforms.map(p => ({
      key: p,
      platform: p,
      successRate: dimComp.success_rate?.[p] ?? platformResults.find(r => r.platform === p)?.success_rate_score,
      quality: dimComp.quality?.[p] ?? platformResults.find(r => r.platform === p)?.quality_score,
      experience: dimComp.experience?.[p] ?? platformResults.find(r => r.platform === p)?.experience_score,
      e2ePassRate: dimComp.e2e_pass_rate?.[p],
    }))

    const metricColumns = [
      { title: '平台', dataIndex: 'platform', key: 'platform', render: p => <Tag color={PLATFORM_COLORS[p] || '#1890ff'}>{PLATFORM_LABELS[p] || p}</Tag> },
      { title: '成功率', dataIndex: 'successRate', key: 'successRate', render: v => safeFormat(v, '%') },
      { title: '功能完整性', dataIndex: 'quality', key: 'quality', render: v => safeFormat(v, '分') },
      { title: '体验', dataIndex: 'experience', key: 'experience', render: v => safeFormat(v, '分') },
      { title: 'E2E 通过率', dataIndex: 'e2ePassRate', key: 'e2ePassRate', render: v => v != null ? safeFormat(v * 100, '%') : '--' },
    ]
    
    return {
      key: sampleId,
      label: (
        <Space size="middle">
          <Text strong>{sampleTitle}</Text>
          <Tag color={consistencyColor(consistencyScore)}>
            一致性 {safeFormat(consistencyScore, '%')}
          </Tag>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {platforms.length} 个平台
          </Text>
        </Space>
      ),
      children: (
        <div>
          {/* 截图横排 */}
          {Object.keys(screenshots).length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <Text strong style={{ marginBottom: 8, display: 'block' }}>启动截图对比</Text>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                {platforms.map(p => {
                  const path = screenshots[p]
                  if (!path) return null
                  const url = buildScreenshotUrl(sampleId, path)
                  return (
                    <div key={p} style={{ textAlign: 'center' }}>
                      <Tag color={PLATFORM_COLORS[p] || '#1890ff'} style={{ marginBottom: 4 }}>
                        {PLATFORM_LABELS[p] || p}
                      </Tag>
                      {url ? (
                        <LazyImage
                          src={url}
                          alt={`${sampleTitle} - ${PLATFORM_LABELS[p] || p}`}
                          width={180}
                          height={320}
                          fallback="/static/placeholder.png"
                        />
                      ) : (
                        <div style={{
                          width: 180,
                          height: 320,
                          background: '#f5f5f5',
                          border: '1px solid #e8e8e8',
                          borderRadius: 4,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: '#bbb',
                        }}>
                          无截图
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          <Table
            dataSource={metricRowData}
            columns={metricColumns}
            size="small"
            pagination={false}
            style={{ marginBottom: 16 }}
          />

          {/* 评测详情展开区 */}
          <Text strong style={{ marginBottom: 8, display: 'block' }}>评测详情：</Text>
          <EvaluationDetailPanel
            sampleId={sampleId}
            groupedResults={platformResults}
            platforms={platforms}
          />
        </div>
      ),
    }
  })

  return (
    <div style={{ padding: '0 0 24px 0' }}>
      {/* 页面标题 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24 }}>
        <span style={{ display: 'inline-block', width: 4, height: 24, borderRadius: 2, background: '#52c41a' }} />
        <Title level={4} style={{ margin: 0 }}>多端一致性对比报告</Title>
        <Tag color="blue">{platforms.length} 个平台</Tag>
        <Text type="secondary">{platforms.map(p => PLATFORM_LABELS[p] || p).join(' / ')}</Text>
      </div>

      {/* 1. 顶层概览区 — 4张指标卡片 */}
      <div className="score-cards" style={{ marginBottom: 24 }}>
        <Row gutter={[16, 16]}>
          {overviewCards.map(card => (
            <Col xs={24} sm={12} md={6} key={card.title}>
              <Card
                className="score-card-item"
                style={{ background: '#fff', borderRadius: '16px' }}
                styles={{ body: { padding: '20px' } }}
              >
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: '12px' }}>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: '32px',
                      height: '32px',
                      borderRadius: '8px',
                      background: `${card.iconColor}15`,
                      color: card.iconColor,
                      fontSize: '16px',
                      marginRight: '10px',
                    }}
                  >
                    {card.icon}
                  </span>
                  <span style={{ color: '#6c757d', fontSize: '13px', fontWeight: 500 }}>{card.title}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px' }}>
                  <span
                    className="score-card-value"
                    style={{
                      fontSize: '36px',
                      fontWeight: 700,
                      lineHeight: 1.2,
                      background: card.valueGradient,
                      WebkitBackgroundClip: 'text',
                      WebkitTextFillColor: 'transparent',
                    }}
                  >
                    {safeFormat(card.value, '', 1)}
                  </span>
                  <span style={{ color: '#6c757d', fontSize: '13px', fontWeight: 500 }}>{card.suffix}</span>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      </div>

      {/* 2. 平台对比总览表 */}
      <div className="report-section">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <span style={{ display: 'inline-block', width: 4, height: 18, borderRadius: 2, background: '#6366f1' }} />
          <span style={{ fontSize: 16, fontWeight: 700, color: '#1f2937' }}>平台对比总览</span>
        </div>
        <Table
          dataSource={platformTableData}
          columns={platformTableColumns}
          size="small"
          pagination={false}
        />
      </div>

      {/* 3. 样本级多端对比卡片 */}
      {sampleComparisonItems.length > 0 ? (
        <div className="report-section">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <span style={{ display: 'inline-block', width: 4, height: 18, borderRadius: 2, background: '#10b981' }} />
            <span style={{ fontSize: 16, fontWeight: 700, color: '#1f2937' }}>样本级多端对比</span>
            <Text type="secondary" style={{ fontSize: 13 }}>共 {sampleComparisonItems.length} 个样本</Text>
          </div>
          <Collapse size="large" items={sampleComparisonItems} />
        </div>
      ) : (
        <div className="report-section">
          <Empty description="无跨平台对比数据" />
        </div>
      )}
    </div>
  )
}