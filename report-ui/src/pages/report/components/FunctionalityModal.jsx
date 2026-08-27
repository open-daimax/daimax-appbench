import React, { useState } from 'react'
import { Drawer, Tag, Button, Empty, Progress, Typography, Tooltip } from 'antd'
import { FileTextOutlined, CloseOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { getSampleScreenshots, getSampleMeta, getTestCaseDefs, getE2eReportUrl } from '../../../data/local'

function getCaseScreenshots(screenshots, tcId) {
  if (!Array.isArray(screenshots)) return []
  return screenshots.filter((s) => s.tc_id === tcId)
}

// 确保字段值为数组（兼容后端返回字符串或其他非数组类型）
function ensureArray(val) {
  if (Array.isArray(val)) return val
  if (typeof val === 'string' && val.trim()) return val.split('\n').map((s) => s.trim()).filter(Boolean)
  return []
}

function formatDuration(seconds) {
  if (seconds == null) return '-'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}m${s}s`
}

export default function FunctionalityModal({ visible, onClose, record, selectedPlatforms }) {
  const [lightboxVisible, setLightboxVisible] = useState(false)
  const [lightboxImage, setLightboxImage] = useState(null)
  const [lightboxTitle, setLightboxTitle] = useState('')

  const sampleId = record?.sample_id || ''
  const recordPlatform = record?.platform || ''
  // 需求描述 / 用例定义 / 截图均来自注入数据，同步取用，无加载态与竞态
  const sampleMeta = React.useMemo(() => (sampleId ? getSampleMeta(sampleId) : null), [sampleId])
  const tcDefinitions = React.useMemo(
    () => (sampleId ? getTestCaseDefs(sampleId, recordPlatform) : []),
    [sampleId, recordPlatform],
  )
  const screenshots = React.useMemo(
    () => (sampleId ? getSampleScreenshots(sampleId, selectedPlatforms) : []),
    [sampleId, selectedPlatforms],
  )

  const { Text } = Typography

  // 核心功能覆盖率渲染
  const renderCoreFunctions = () => {
    const coverage = record?.core_function_coverage
    const hasCoverage = coverage && coverage.function_results && Object.keys(coverage.function_results).length > 0
    const coreFunctions = ensureArray(sampleMeta?.core_functions)
    const hasCoreFunctions = coreFunctions.length > 0

    if (!hasCoverage && !hasCoreFunctions) return null

    // 覆盖率进度条颜色
    const getCoverageColor = (rate) => {
      if (rate >= 0.8) return '#52c41a'
      if (rate >= 0.5) return '#fa8c16'
      return '#ff4d4f'
    }

    // 状态 Tag 配置
    const statusConfig = {
      covered: { color: 'success', label: '已通过' },
      failed: { color: 'error', label: '未通过' },
      missing: { color: 'default', label: '未覆盖' },
    }

    return (
      <div className="tc-core-functions">
        <h5>核心功能</h5>
        {hasCoverage && (
          <div className="tc-coverage-summary">
            <div className="tc-coverage-progress">
              <Progress
                type="circle"
                size={64}
                percent={Math.round((coverage.coverage_rate || 0) * 100)}
                strokeColor={getCoverageColor(coverage.coverage_rate || 0)}
                format={(percent) => (
                  <span style={{ fontSize: 16, fontWeight: 600 }}>{percent}%</span>
                )}
              />
              <div className="tc-coverage-stats">
                <Text strong>{coverage.covered_functions}/{coverage.total_functions} 核心功能已通过</Text>
                <div className="tc-coverage-detail">
                  <Tag color="success" style={{ margin: 0 }}>已通过 {coverage.covered_functions}</Tag>
                  <Tag color="error" style={{ margin: 0 }}>未通过 {coverage.failed_functions}</Tag>
                  <Tag color="default" style={{ margin: 0 }}>未覆盖 {coverage.missing_functions}</Tag>
                </div>
              </div>
            </div>
            <div className="tc-coverage-list">
              {Object.entries(coverage.function_results).map(([fnName, fnResult]) => {
                const cfg = statusConfig[fnResult.status] || statusConfig.missing
                // 从 e2e_test_cases 查找关联测试用例的名称
                const matchedTcId = fnResult.matched_tc
                const tcName = fnResult.matched_tc_name
                return (
                  <div key={fnName} className="tc-coverage-item">
                    <div className="tc-coverage-fn-left">
                      <span className="tc-coverage-fn-name">{fnName}</span>
                      {matchedTcId && (
                        <Tag className="tc-coverage-tc-tag" color="processing">
                          {matchedTcId}{tcName ? ` ${tcName}` : ''}
                        </Tag>
                      )}
                    </div>
                    <Tag color={cfg.color}>{cfg.label}</Tag>
                  </div>
                )
              })}
            </div>
          </div>
        )}
        {!hasCoverage && hasCoreFunctions && (
          <ul>
            {coreFunctions.map((fn, i) => <li key={i}>{fn}</li>)}
          </ul>
        )}
      </div>
    )
  }

  if (!record) return null

  const { sample_id, sample_title, platform, e2e_test_cases } = record
  const hasCases = Array.isArray(e2e_test_cases) && e2e_test_cases.length > 0

  const openLightbox = (url, title) => {
    setLightboxImage(url)
    setLightboxTitle(title)
    setLightboxVisible(true)
  }

  const closeLightbox = () => {
    setLightboxVisible(false)
    setLightboxImage(null)
    setLightboxTitle('')
  }

  const drawerTitle = `功能详情 - ${sample_title || sample_id} (${platform})`

  return (
    <>
      <Drawer
        title={drawerTitle}
        placement="right"
        width="100%"
        open={visible}
        onClose={onClose}
        destroyOnClose
        className="tc-drawer"
      >
        {hasCases ? (
          <div className="tc-card-list">
            {/* 需求描述区块 */}
            {sampleMeta && sampleMeta.requirement && (
              <div className="tc-requirement-section">
                <h4>📋 需求描述</h4>
                <pre className="tc-requirement-text">{sampleMeta.requirement}</pre>
                {renderCoreFunctions()}
                {ensureArray(sampleMeta.constraints).length > 0 && (
                  <div className="tc-core-functions">
                    <h5>约束条件</h5>
                    <ul>
                      {ensureArray(sampleMeta.constraints).map((c, i) => <li key={i}>{c}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {e2e_test_cases.map((tc) => {
              const caseShots = getCaseScreenshots(screenshots, tc.test_case_id)
              const isFail = tc.status === 'FAIL'
              const caseName = tc.test_case_name || tc.test_case_id
              const caseDesc = tc.test_case_description || ''

              return (
                <div
                  key={tc.test_case_id}
                  className={`tc-card ${isFail ? 'tc-card-fail' : ''}`}
                >
                  <div className="tc-card-header">
                    <span className="tc-card-id">{tc.test_case_id}</span>
                    <span className="tc-card-name">{caseName}</span>
                    <Tag color={tc.status === 'PASS' ? 'success' : 'error'}>
                      {tc.status}
                    </Tag>
                    {tc.manual_override && (
                      <Tooltip title="已人工纠正">
                        <ExclamationCircleOutlined style={{ color: '#faad14', marginLeft: 4, fontSize: 14 }} />
                      </Tooltip>
                    )}
                    {tc.duration != null && (
                      <span className="tc-card-duration">
                        {formatDuration(tc.duration)}
                      </span>
                    )}
                  </div>

                  {caseDesc && (
                    <div className="tc-card-description">
                      <span className="tc-card-section-label">预期</span>
                      <span className="tc-description-text">{caseDesc}</span>
                    </div>
                  )}

                  {/* 测试步骤与预期结果（来自测试用例定义） */}
                  {(() => {
                    const tcDef = tcDefinitions.find(d => d.id === tc.test_case_id)
                    if (!tcDef) return null
                    const hasSteps = tcDef.steps && tcDef.steps.length > 0
                    const hasExpected = !!tcDef.expected_result
                    if (!hasSteps && !hasExpected) return null
                    return (
                      <div className="tc-card-definition">
                        {hasSteps && (
                          <div className="tc-card-steps">
                            <span className="tc-def-label">测试步骤：</span>
                            <ol>
                              {tcDef.steps.map((step, i) => <li key={i}>{step}</li>)}
                            </ol>
                          </div>
                        )}
                        {hasExpected && (
                          <div className="tc-card-expected">
                            <span className="tc-def-label">预期结果：</span>
                            <span>{tcDef.expected_result}</span>
                          </div>
                        )}
                      </div>
                    )
                  })()}

                  {caseShots.length > 0 && (
                    <div className="tc-card-screenshots">
                      <span className="tc-card-section-label">截图</span>
                      <div className="tc-screenshot-scroll">
                        {caseShots.map((shot, idx) => (
                          <div
                            key={idx}
                            className="tc-screenshot-item"
                            onClick={() => shot.url ? openLightbox(shot.url, shot.step_name) : null}
                            style={{ cursor: shot.url ? 'pointer' : 'default' }}
                          >
                            {shot.url ? (
                              <img
                                src={shot.url}
                                alt={shot.step_name}
                                className="tc-screenshot-thumb"
                                loading="lazy"
                                onError={(e) => {
                                  e.target.style.display = 'none'
                                  e.target.nextSibling.style.display = 'flex'
                                }}
                              />
                            ) : null}
                            <div
                              style={{
                                display: shot.url ? 'none' : 'flex',
                                width: 160,
                                height: 160,
                                background: '#f5f5f5',
                                borderRadius: 6,
                                border: '1px solid #e8e8e8',
                                alignItems: 'center',
                                justifyContent: 'center',
                                fontSize: 11,
                                color: '#aaa',
                                flexDirection: 'column',
                                gap: 4,
                              }}
                            >
                              <span>截图加载失败</span>
                              <span style={{ wordBreak: 'break-all', padding: '0 8px', textAlign: 'center' }}>{shot.step_name || shot.filename}</span>
                            </div>
                            <div className="tc-screenshot-step-label">{shot.step_name || shot.filename}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {tc.details && (
                    <div className={`tc-card-conclusion ${isFail ? 'tc-conclusion-fail' : 'tc-conclusion-pass'}`}>
                      <span className="tc-conclusion-label">
                        {isFail ? '失败原因' : '通过原因'}
                      </span>
                      <div className="tc-conclusion-text">
                        {tc.details}
                      </div>
                    </div>
                  )}

                  {/* 导出目录内没有对应文件时 getE2eReportUrl 返回 null，直接隐藏入口 */}
                  {getE2eReportUrl(tc.report_path) && (
                    <div className="tc-card-footer">
                      <Button
                        type="link"
                        size="small"
                        icon={<FileTextOutlined />}
                        href={getE2eReportUrl(tc.report_path)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        查看详细报告 →
                      </Button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        ) : (
          <Empty description="暂无E2E测试用例数据" />
        )}
      </Drawer>

      <Drawer
        open={lightboxVisible}
        onClose={closeLightbox}
        width="100%"
        className="lightbox-drawer"
        styles={{ body: { padding: 0, display: 'flex', justifyContent: 'center', alignItems: 'center', background: 'rgba(0,0,0,0.85)', minHeight: '100vh' } }}
        closable={true}
        destroyOnClose
      >
        <div className="lightbox-container-fullscreen">
          <Button
            type="text"
            className="lightbox-close"
            icon={<CloseOutlined />}
            onClick={closeLightbox}
          />
          {lightboxImage && (
            <img
              src={lightboxImage}
              alt={lightboxTitle}
              className="lightbox-image-fullscreen"
            />
          )}
          {lightboxTitle && (
            <div className="lightbox-title">{lightboxTitle}</div>
          )}
        </div>
      </Drawer>
    </>
  )
}
