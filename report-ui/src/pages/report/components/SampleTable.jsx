import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { Table, Button, Tag, Row, Col, Tooltip, Modal, Typography, Descriptions, Alert, List, Drawer, Space, message } from 'antd'
import { EyeOutlined, CloseOutlined, ExpandOutlined, CompressOutlined, RightOutlined, ExperimentOutlined, LinkOutlined } from '@ant-design/icons'
import { formatDuration, formatBytes } from '../utils'
import { getDatasetDisplayName } from '../../../utils/displayNames'
import { getAestheticsTrace, getScreenshotUrl, getWorkspaceFileUrl } from '../../../data/local'
import LazyImage from './LazyImage'

/* -------------------------------------------------------------------------
 * SampleTable 性能优化总览
 *
 * 1) 单一滚动上下文：表格不设 scroll.y，内容自然撑高随页面主滚动条
 *    整体滚动（避免页内双滚动）；渲染压力由下方 2) 的展开行懒渲染
 *    与“折叠全部”按钮化解（收起状态下仅渲染摘要行）。
 *
 * 2) 展开行懒渲染：废弃 `defaultExpandAllRows: true`，改为受控的
 *    `expandedRowKeys`。expandedRowRender 仅会被 antd 在该 key 展开时调用，
 *    折叠后销毁 DOM（释放图片/弹窗按钮等）。同时提供"展开/折叠全部"按钮，
 *    保留快速浏览能力。
 *
 * 3) 截图懒加载：所有缩略图统一通过 <LazyImage>，仅在视口内才发起请求；
 *    失败回退由 antd <Image> 处理。
 *
 * 4) 列渲染优化：columns 通过 useMemo 缓存为稳定引用；
 *    expandedRowRender 通过 useCallback 稳定；展开行内容抽离为
 *    React.memo 包裹的 ExpandedRowContent，配合稳定的回调引用，
 *    可使滚动过程中已展开行避免无谓的重渲染。
 *
 * 5) 数据层优化：父级已用 useMemo 缓存 filteredResults；
 *    本组件再无重复 map/filter，所有派生数据均来自单次入参 sampleResults。
 *
 * ------------------------------------------------------------------------ */

const SCREENSHOT_FALLBACK =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='200' viewBox='0 0 120 200'%3E%3Crect fill='%23f5f5f5' width='120' height='200'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' fill='%23999' font-size='12'%3E截图加载失败%3C/text%3E%3C/svg%3E"

function formatScore(v) {
  if (v === undefined || v === null) return '-'
  const n = Number(v)
  if (!Number.isFinite(n)) return '-'
  return n.toFixed(1)
}

function rowKeyOf(record) {
  return `${record.sample_id}-${record.platform}`
}

/* 复制文本到剪贴板：优先 Clipboard API，非安全上下文（http 部署）回退 execCommand */
async function copyTextToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    if (!document.execCommand('copy')) {
      throw new Error('execCommand copy failed')
    }
  } finally {
    document.body.removeChild(textarea)
  }
}

/* -------------------------------------------------------------------------
 * ExpandedRowContent —— 展开行渲染内容
 * 抽离为独立组件并用 React.memo 包装；只要 record 与回调引用稳定，
 * 滚动/筛选触发的父级 rerender 不会影响已展开行的子树。
 * ------------------------------------------------------------------------ */
const ExpandedRowContent = React.memo(function ExpandedRowContent({
  record,
  onShowFunctionality,
  onShowStability,
  onShowAesthetics,
  onShowBackend,
}) {
  return (
    <div className="detail-grid">
      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <div className="detail-section">
            <div className="detail-section-title">成功率详情</div>
            <div className="detail-item">
              <span className="detail-label">首次生成成功率</span>
              <span className="detail-value">{formatScore(record.success_rate_score)}%</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">说明</span>
              <span className="detail-reason">{record.success_rate_reason || '-'}</span>
            </div>
          </div>
        </Col>
        <Col xs={24} md={8}>
          <div className="detail-section">
            <div className="detail-section-title">功能完整性详情</div>
            <div className="detail-item">
              <span className="detail-label">用例完整性</span>
              <span className="detail-value">
                {formatScore(record.functionality_score)}分
                <Button
                  type="link"
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={() => onShowFunctionality(record)}
                >
                  查看详情
                </Button>
                {record.launch_screenshot ? (
                  <div style={{ marginTop: 8 }}>
                    <LazyImage
                      src={record.launch_screenshot}
                      alt="启动截图"
                      width={120}
                      height={200}
                      fallback={SCREENSHOT_FALLBACK}
                      imgProps={{
                        style: { borderRadius: 4, border: '1px solid #e8e8e8' },
                      }}
                    />
                  </div>
                ) : record.platform === 'miniprogram' ? (
                  <div
                    style={{
                      marginTop: 8,
                      width: 120,
                      height: 80,
                      background: '#fafafa',
                      borderRadius: 4,
                      border: '1px dashed #d9d9d9',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <span style={{ fontSize: 11, color: '#999', textAlign: 'center', padding: 8 }}>
                      小程序/H5无启动截图
                    </span>
                  </div>
                ) : null}
              </span>
            </div>
            <div className="detail-item">
              <span className="detail-label">运行稳定性</span>
              <span className="detail-value">
                {formatScore(record.stability_score)}分
                <Button
                  type="link"
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={() => onShowStability(record)}
                >
                  查看详情
                </Button>
              </span>
            </div>
            {/* 子指标2.5: 后端完整性 - 始终显示 */}
            <div className="detail-item">
              <span className="detail-label">后端完整性</span>
              <span className="detail-value">
                {record.requires_backend === false
                  ? <span style={{ color: '#52c41a' }}>无需后端</span>
                  : record.backend_completeness != null
                    ? (
                      <>
                        {formatScore(record.backend_completeness)}分
                        <span style={{ marginLeft: 8, color: '#888' }}>{record.backend_completeness_reason}</span>
                        <Button
                          type="link"
                          size="small"
                          onClick={() => onShowBackend(record)}
                        >
                          查看详情
                        </Button>
                      </>
                    )
                    : <span style={{ color: '#aaa' }}>N/A</span>
                }
              </span>
            </div>
            <div className="detail-item">
              <span className="detail-label">崩溃/ANR/白屏</span>
              <span className="detail-value">
                <Tag color={record.crash_count > 0 ? 'error' : 'success'}>崩溃 {record.crash_count ?? 0}</Tag>
                <Tag color={record.anr_count > 0 ? 'warning' : 'success'}>ANR {record.anr_count ?? 0}</Tag>
                <Tag color={record.white_screen_count > 0 ? 'warning' : 'success'}>白屏 {record.white_screen_count ?? 0}</Tag>
              </span>
            </div>
          </div>
        </Col>
        <Col xs={24} md={8}>
          <div className="detail-section">
            <div className="detail-section-title">体验详情</div>
            <div className="detail-item">
              <span className="detail-label">端到端耗时</span>
              <span className="detail-value">{formatDuration(record.duration_ms)}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">说明</span>
              <span className="detail-reason">端到端耗时为代码生成时间</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">包大小</span>
              <span className="detail-value">{formatBytes(record.package_size_bytes, record.platform)}</span>
            </div>
            {/* UI美观度评分 */}
            <div className="detail-item">
              <span className="detail-label">UI美观度</span>
              <span className="detail-value">
                {record.aesthetics_score != null
                  ? <>
                      {formatScore(record.aesthetics_score)} / 10
                      {record.aesthetics_rule_version && (
                        <span style={{ fontSize: '11px', color: '#999', marginLeft: 6 }}>
                          v{record.aesthetics_rule_version}
                        </span>
                      )}
                      <Button
                        type="link"
                        size="small"
                        icon={<EyeOutlined />}
                        onClick={() => onShowAesthetics(record)}
                        style={{ marginLeft: 4 }}
                      >
                        查看详情
                      </Button>
                    </>
                  : '-'
                }
              </span>
            </div>
            {record.aesthetics_reason && (
              <div className="detail-item">
                <span className="detail-label">评语</span>
                <span className="detail-reason">{record.aesthetics_reason}</span>
              </div>
            )}
            {record.aesthetics_issues && record.aesthetics_issues.length > 0 && (
              <div className="detail-item">
                <span className="detail-label">问题项</span>
                <span className="detail-reason">
                  {record.aesthetics_issues.slice(0, 3).join('；')}
                </span>
              </div>
            )}
            {/* Token/花销仅部分生成器提供，拿不到数据时整行隐藏，不对外展示占位符 */}
            {(record.token_total || 0) > 0 && (
              <div className="detail-item">
                <span className="detail-label">Token消耗</span>
                <span className="detail-value">
                  输入 {record.token_input != null ? Math.round(record.token_input).toLocaleString('zh-CN') : '-'} / 输出 {record.token_output != null ? Math.round(record.token_output).toLocaleString('zh-CN') : '-'} / 总计 {Math.round(record.token_total).toLocaleString('zh-CN')}
                </span>
              </div>
            )}
            {record.cost_usd != null && record.cost_usd > 0 && (
              <div className="detail-item">
                <span className="detail-label">花销</span>
                <span className="detail-value">${record.cost_usd.toFixed(4)}</span>
              </div>
            )}
          </div>
        </Col>
      </Row>
    </div>
  )
})

/* -------------------------------------------------------------------------
 * AestheticsDetailModal —— 美观度评测详情弹窗
 * 抽出为独立组件并 memo，按需挂载（仅 visible 时渲染主体）。
 * ------------------------------------------------------------------------ */
const AestheticsDetailModal = React.memo(function AestheticsDetailModal({
  visible,
  onClose,
  record,
  trace,
  onPreviewImage,
}) {
  return (
    <Modal
      title={`UI美观度评测详情 - ${record?.sample_id || ''} (${record?.platform || ''})`}
      open={visible}
      onCancel={onClose}
      footer={null}
      width={720}
      destroyOnClose
    >
      {!trace && (
        <Alert type="warning" message="暂无 trace 数据：本次评测未记录该样本的美观度明细" />
      )}
      {trace && (
        <>
          <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
            <Descriptions.Item label="总分" span={2}>
              <strong style={{ fontSize: 18 }}>{trace.parsed_result?.overall ?? '-'}</strong>
              <span style={{ color: '#888', marginLeft: 4 }}>/ 10</span>
            </Descriptions.Item>
            <Descriptions.Item label="评语" span={2}>
              {trace.parsed_result?.comment || '-'}
            </Descriptions.Item>
          </Descriptions>

          {trace.parsed_result?.dimensions && (
            <>
              <div style={{ fontWeight: 600, marginBottom: 8, color: '#444' }}>五维度评分</div>
              <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
                <Descriptions.Item label="配色和谐度">
                  {trace.parsed_result.dimensions.color_harmony ?? '-'}
                </Descriptions.Item>
                <Descriptions.Item label="布局质量">
                  {trace.parsed_result.dimensions.layout_quality ?? '-'}
                </Descriptions.Item>
                <Descriptions.Item label="视觉层次">
                  {trace.parsed_result.dimensions.visual_hierarchy ?? '-'}
                </Descriptions.Item>
                <Descriptions.Item label="排版">
                  {trace.parsed_result.dimensions.typography ?? '-'}
                </Descriptions.Item>
                <Descriptions.Item label="专业度" span={2}>
                  {trace.parsed_result.dimensions.professionalism ?? '-'}
                </Descriptions.Item>
              </Descriptions>
            </>
          )}

          {trace.parsed_result?.issues && trace.parsed_result.issues.length > 0 && (
            <>
              <div style={{ fontWeight: 600, marginBottom: 8, color: '#444' }}>
                扣分明细（共 {trace.parsed_result.issues.length} 项）
              </div>
              <List
                size="small"
                bordered
                dataSource={trace.parsed_result.issues}
                renderItem={(item, idx) => (
                  <List.Item>
                    <span style={{ color: '#888', marginRight: 8 }}>{idx + 1}.</span>{item}
                  </List.Item>
                )}
                style={{ marginBottom: 16 }}
              />
            </>
          )}

          {trace.selected_frames && trace.selected_frames.length > 0 && (
            <>
              <div style={{ fontWeight: 600, marginBottom: 8, color: '#444' }}>
                关键截图（共 {trace.frame_count ?? trace.selected_frames.length} 帧）
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
                {trace.selected_frames.map((frame, idx) => {
                  const filename = frame.split('/').pop()
                  const imgUrl = record ? getScreenshotUrl(record.sample_id, filename) : null
                  return (
                    <div
                      key={idx}
                      className="tc-screenshot-item"
                      onClick={() => imgUrl && onPreviewImage(imgUrl, filename)}
                      style={{ cursor: imgUrl ? 'pointer' : 'default' }}
                    >
                      {imgUrl ? (
                        <img
                          src={imgUrl}
                          alt={filename}
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
                          display: imgUrl ? 'none' : 'flex',
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
                        <span>图片加载失败</span>
                        <span style={{ wordBreak: 'break-all', padding: '0 8px', textAlign: 'center' }}>{filename}</span>
                      </div>
                      <div
                        className="tc-screenshot-step-label"
                        style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      >
                        {filename}
                      </div>
                    </div>
                  )
                })}
              </div>
            </>
          )}

          <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
            <Descriptions.Item label="评测时间" span={2}>
              {trace.timestamp || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="模型">
              {trace.api_request?.model || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="规则版本">
              {trace.rule_version || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="平台">
              {trace.platform || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="图片数量">
              {trace.api_request?.image_count ?? '-'}
            </Descriptions.Item>
          </Descriptions>

          {trace.error && (
            <Alert
              type="error"
              message="评测出现错误"
              description={String(trace.error)}
              style={{ marginBottom: 16 }}
            />
          )}
        </>
      )}
    </Modal>
  )
})

/* -------------------------------------------------------------------------
 * BackendDetailModal —— 后端完整性详情弹窗
 * ------------------------------------------------------------------------ */
const BackendDetailModal = React.memo(function BackendDetailModal({ visible, onClose, record }) {
  const dataSource = useMemo(() => {
    if (!record?.backend_requests) return []
    return record.backend_requests.map((r, idx) => {
      if (typeof r === 'string') {
        return { key: idx, url: r, method: '-', status: '-', requestBody: '-', responseBody: '-' }
      }
      return { key: idx, ...r }
    })
  }, [record])

  const columns = useMemo(() => [
    { title: 'Method', dataIndex: 'method', key: 'method', width: 80 },
    {
      title: 'URL',
      dataIndex: 'url',
      key: 'url',
      render: (url) => (
        <Typography.Paragraph copyable ellipsis style={{ marginBottom: 0, maxWidth: 300 }}>
          {url}
        </Typography.Paragraph>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 70,
      render: (status) => {
        if (status == null || status === '-') return '-'
        const color = status >= 200 && status < 300 ? 'success' : status >= 400 ? 'error' : 'warning'
        return <Tag color={color}>{status}</Tag>
      },
    },
    {
      title: 'Headers',
      dataIndex: 'requestHeaders',
      key: 'requestHeaders',
      width: 200,
      render: (headers) => {
        if (!headers || Object.keys(headers).length === 0) return <span style={{ color: '#aaa' }}>N/A</span>
        const importantKeys = ['apikey', 'authorization', 'x-client-info', 'content-type', 'x-supabase-api-version']
        const filtered = Object.entries(headers).filter(([k]) =>
          importantKeys.includes(k.toLowerCase())
        )
        const display = filtered.length > 0 ? filtered : Object.entries(headers).slice(0, 5)
        return (
          <Typography.Paragraph
            ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
            style={{ marginBottom: 0, fontSize: 11, fontFamily: 'monospace' }}
          >
            {display.map(([k, v]) => `${k}: ${v}`).join('\n')}
          </Typography.Paragraph>
        )
      },
    },
    {
      title: 'Request Body',
      dataIndex: 'requestBody',
      key: 'requestBody',
      width: 220,
      render: (body) => {
        if (!body) return <span style={{ color: '#aaa' }}>N/A</span>
        return (
          <Typography.Paragraph
            ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
            style={{ marginBottom: 0, fontSize: 12 }}
          >
            {body}
          </Typography.Paragraph>
        )
      },
    },
    {
      title: 'Response Body',
      dataIndex: 'responseBody',
      key: 'responseBody',
      width: 220,
      render: (body) => {
        if (!body) return <span style={{ color: '#aaa' }}>N/A</span>
        return (
          <Typography.Paragraph
            ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
            style={{ marginBottom: 0, fontSize: 12 }}
          >
            {body}
          </Typography.Paragraph>
        )
      },
    },
  ], [])

  return (
    <Modal
      title={`后端完整性详情 - ${record?.sample_title || record?.sample_id || ''}`}
      open={visible}
      onCancel={onClose}
      footer={null}
      width={800}
      destroyOnClose
    >
      {record && (
        <>
          <div style={{ marginBottom: 16, padding: 16, background: '#fafafa', borderRadius: 8 }}>
            <div style={{ marginBottom: 8 }}>
              <span style={{ fontWeight: 500 }}>评分：</span>
              <span style={{ fontSize: 18, fontWeight: 600, color: record.backend_completeness >= 60 ? '#52c41a' : '#f5222d' }}>
                {record.backend_completeness != null ? `${formatScore(record.backend_completeness)}分` : 'N/A'}
              </span>
            </div>
            <div>
              <span style={{ fontWeight: 500 }}>评估说明：</span>
              <span style={{ color: '#666' }}>{record.backend_completeness_reason || '暂无评估说明'}</span>
            </div>
          </div>
          {record.backend_requests && record.backend_requests.length > 0 ? (
            <>
              <div style={{ marginBottom: 8, fontWeight: 500 }}>后端请求记录：</div>
              <Table
                dataSource={dataSource}
                columns={columns}
                size="small"
                pagination={false}
                scroll={{ x: 'max-content', y: 400 }}
              />
            </>
          ) : (
            <div style={{ color: '#999', textAlign: 'center', padding: '24px 0' }}>
              暂无后端请求记录
            </div>
          )}
        </>
      )}
    </Modal>
  )
})

/* -------------------------------------------------------------------------
 * SampleTable —— 主组件
 * ------------------------------------------------------------------------ */
export default function SampleTable({ sampleResults, excludedSamples, sampleTitleMap = {}, onShowFunctionality, onShowStability }) {
  // 入参防御：始终归一化为数组，确保 Hooks 调用顺序在多次渲染间保持稳定
  const safeResults = useMemo(
    () => (Array.isArray(sampleResults) ? sampleResults : []),
    [sampleResults]
  )

  // 失败样本归一化
  const safeExcluded = useMemo(
    () => (Array.isArray(excludedSamples) ? excludedSamples : []),
    [excludedSamples]
  )

  // 合并数据源：成功样本 + 失败样本（失败排后面），统一供表格渲染
  const mergedResults = useMemo(() => {
    return [...safeResults, ...safeExcluded]
  }, [safeResults, safeExcluded])

  // 后端详情弹窗
  const [backendDetailVisible, setBackendDetailVisible] = useState(false)
  const [currentBackendRecord, setCurrentBackendRecord] = useState(null)

  // 美观度详情弹窗（trace 已随报告注入，无异步加载）
  const [aestheticsDetailVisible, setAestheticsDetailVisible] = useState(false)
  const [currentAestheticsRecord, setCurrentAestheticsRecord] = useState(null)
  const [aestheticsTrace, setAestheticsTrace] = useState(null)

  // 截图灯箱
  const [lightboxVisible, setLightboxVisible] = useState(false)
  const [lightboxImage, setLightboxImage] = useState(null)
  const [lightboxTitle, setLightboxTitle] = useState(null)

  // 受控的展开行 key 集合：通过状态精确控制哪些行被渲染。
  // 默认策略：行数较少时全部展开（保留旧 UX），超过阈值时全部折叠（性能优先）。
  const initialExpandedKeys = useMemo(() => {
    if (safeResults.length === 0 && safeExcluded.length === 0) return []
    // 只默认展开成功样本，失败样本不展开
    return safeResults.map(rowKeyOf)
  }, [safeResults, safeExcluded])

  const [expandedRowKeys, setExpandedRowKeys] = useState(initialExpandedKeys)

  // 数据集变化时（如父级筛选切换）同步默认展开策略
  useEffect(() => {
    setExpandedRowKeys(initialExpandedKeys)
  }, [initialExpandedKeys])

  /* ---------------- 稳定回调（避免每次渲染产生新引用） ---------------- */

  const openLightbox = useCallback((url, title) => {
    setLightboxImage(url)
    setLightboxTitle(title)
    setLightboxVisible(true)
  }, [])

  const closeLightbox = useCallback(() => {
    setLightboxVisible(false)
    setLightboxImage(null)
    setLightboxTitle(null)
  }, [])

  const handleShowAestheticsDetail = useCallback((record) => {
    setCurrentAestheticsRecord(record)
    setAestheticsTrace(getAestheticsTrace(record.sample_id, record.platform))
    setAestheticsDetailVisible(true)
  }, [])

  const closeAestheticsDetail = useCallback(() => setAestheticsDetailVisible(false), [])

  const handleShowBackend = useCallback((record) => {
    setCurrentBackendRecord(record)
    setBackendDetailVisible(true)
  }, [])

  const closeBackendDetail = useCallback(() => setBackendDetailVisible(false), [])

  const handleExpandAll = useCallback(() => {
    setExpandedRowKeys(mergedResults.map(rowKeyOf))
  }, [mergedResults])

  const handleCollapseAll = useCallback(() => {
    setExpandedRowKeys([])
  }, [])

  const onExpandedRowsChange = useCallback((keys) => {
    // antd 传入的是当前所有展开行 key 数组，直接设置即可
    setExpandedRowKeys(keys)
  }, [])

  /* ---------------- "复制链接"回调 ---------------- */
  // 预览链接来自后端报告下发时回填的 h5_url（生成阶段发布的产物链接）
  const handleCopyLink = useCallback(async (record) => {
    const url = record?.h5_url
    if (!url) return
    try {
      await copyTextToClipboard(url)
      message.success('预览链接已复制')
    } catch (err) {
      message.error('复制失败，请手动复制：' + url)
    }
  }, [])

  /* ---------------- 列定义（稳定引用） ---------------- */

  const columns = useMemo(() => [
    {
      title: '样本名称',
      dataIndex: 'sample_title',
      key: 'sample_title',
      width: 360,
      ellipsis: true,
      render: (text, record, index) => {
        const rowKey = rowKeyOf(record)
        const isExpanded = expandedRowKeys.includes(rowKey)
        const isExcluded = record.excluded === true
        // 报告缺 sample_title 时用样本集清单标题兜底，仍无标题才回退 sample_id
        const title = text || sampleTitleMap[record.sample_id]
        return (
          <span style={{ display: 'flex', alignItems: 'center' }}>
            <span style={{ color: '#bbb', fontSize: 12, width: 24, flexShrink: 0, textAlign: 'right', marginRight: 8 }}>
              {index + 1}
            </span>
            <RightOutlined
              style={{
                fontSize: 11,
                color: '#999',
                transition: 'transform 0.2s ease',
                transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
                marginRight: 8,
                flexShrink: 0,
              }}
            />
            <span style={isExcluded ? { color: '#999' } : undefined}>
              {title ? `${title}（${record.sample_id}）` : record.sample_id}
              {isExcluded && (
                <Tag color="error" style={{ marginLeft: 8 }}>失败</Tag>
              )}
              {isExcluded && record.sample_overall_status && (
                <Tag color="default" style={{ marginLeft: 4 }}>{record.sample_overall_status}</Tag>
              )}
              {!isExcluded && record.is_deliverable && <Tag color="success" style={{ marginLeft: 8 }}>可交付</Tag>}
              {!isExcluded && record.requires_backend && <Tag color="orange" style={{ marginLeft: 8 }}>需后端</Tag>}
              {/* 执行详情：指向工作区内的报告文件，拿不到相对路径时不展示入口 */}
              {!isExcluded && getWorkspaceFileUrl(record.execution_report_path) && (
                <Tag
                  color="blue"
                  style={{ marginLeft: 8, cursor: 'pointer' }}
                  onClick={(e) => {
                    e.stopPropagation()
                    window.open(getWorkspaceFileUrl(record.execution_report_path), '_blank')
                  }}
                >
                  执行详情
                </Tag>
              )}
              {/* 复制链接：仅在有生成产物预览链接（h5_url）时展示，
                  天然只对产物预览链接类生成器的成功样本出现；
                  复制不依赖后端服务，静态报告同样可用 */}
              {!isExcluded && record.h5_url && (
                <Tooltip title={record.h5_url}>
                  <Tag
                    color="green"
                    icon={<LinkOutlined />}
                    style={{ marginLeft: 8, cursor: 'pointer' }}
                    onClick={(e) => {
                      e.stopPropagation()
                      handleCopyLink(record)
                    }}
                  >
                    复制链接
                  </Tag>
                </Tooltip>
              )}
            </span>
          </span>
        )
      },
    },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 100,
      render: (platform, record) => <Tag color={record.excluded ? 'default' : 'blue'}>{platform}</Tag>,
    },
    {
      title: '分类',
      dataIndex: 'top_category',
      key: 'top_category',
      width: 100,
      // 分类值优先命中中文映射，无法映射时原样展示，缺失显示占位符
      render: (v) => getDatasetDisplayName(v) || '-',
    },
    {
      title: '成功率',
      dataIndex: 'success_rate_score',
      key: 'success_rate_score',
      width: 75,
      render: (v, record) => record.excluded ? '-' : `${formatScore(v)}`,
    },
    {
      title: '功能完整性',
      dataIndex: 'quality_score',
      key: 'quality_score',
      width: 70,
      render: (v, record) => record.excluded ? '-' : `${formatScore(v)}`,
    },
    {
      title: '体验',
      dataIndex: 'experience_score',
      key: 'experience_score',
      width: 70,
      render: (v, record) => record.excluded ? '-' : `${formatScore(v)}`,
    },
  ], [expandedRowKeys, handleCopyLink, sampleTitleMap])

  /* ---------------- 展开行渲染（稳定引用） ---------------- */

  const expandedRowRender = useCallback((record) => {
    if (record.excluded) {
      return (
        <div className="detail-grid" style={{ padding: '12px 16px' }}>
          <Row gutter={[16, 16]}>
            <Col xs={24} md={12}>
              <div className="detail-section">
                <div className="detail-section-title" style={{ color: '#f5222d' }}>失败原因</div>
                <div className="detail-item">
                  <span className="detail-label">排除原因</span>
                  <span className="detail-reason" style={{ color: '#f5222d' }}>{record.exclude_reason || '未知'}</span>
                </div>
                {record.sample_overall_status && (
                  <div className="detail-item">
                    <span className="detail-label">样本状态</span>
                    <span className="detail-value">{record.sample_overall_status}</span>
                  </div>
                )}
              </div>
            </Col>
          </Row>
        </div>
      )
    }
    return (
    <ExpandedRowContent
      record={record}
      onShowFunctionality={onShowFunctionality}
      onShowStability={onShowStability}
      onShowAesthetics={handleShowAestheticsDetail}
      onShowBackend={handleShowBackend}
    />
    )
  }, [onShowFunctionality, onShowStability, handleShowAestheticsDetail, handleShowBackend])

  const expandable = useMemo(() => ({
    expandedRowKeys,
    onExpandedRowsChange,
    expandedRowRender,
    // antd 5.x 支持 showExpandColumn:false，彻底不渲染默认展开列
    // 我们通过整行点击控制展开/折叠，无需占位列
    showExpandColumn: false,
  }), [expandedRowKeys, onExpandedRowsChange, expandedRowRender])

  const rowClassName = useCallback(
    (record) => {
      if (record.excluded) return 'row-excluded'
      return record.is_deliverable ? 'row-pass' : 'row-fail'
    },
    []
  )

  const tableTitle = useCallback(() => (
    <Row align="middle" justify="space-between">
      <Col>
        <strong>样本详情</strong>
        <span style={{ marginLeft: 8, color: '#999', fontWeight: 'normal' }}>
          共 {mergedResults.length} 条（成功 {safeResults.length} · 失败 {safeExcluded.length}） · 已展开 {expandedRowKeys.length}
        </span>
      </Col>
      <Col>
        <Space>
          <Button size="small" icon={<ExpandOutlined />} onClick={handleExpandAll}>展开全部</Button>
          <Button size="small" icon={<CompressOutlined />} onClick={handleCollapseAll}>折叠全部</Button>
        </Space>
      </Col>
    </Row>
  ), [mergedResults.length, safeResults.length, safeExcluded.length, expandedRowKeys.length, handleExpandAll, handleCollapseAll])

  // scroll.x 使用所有列宽之和，避免 'max-content' 让无显式宽度的列吃掉过多空间。
  // 不设 scroll.y：表格自然撑高，随页面主滚动条整体滚动，
  // 避免“样本详情”区域出现独立内层滚动（双滚动体验割裂）。
  // 各列宽度：样本名称 360 + 平台 100 + 分类 100 + 成功率 75 + 功能完整性 70 + 体验 70 = 775
  const TABLE_TOTAL_WIDTH = 775
  const scroll = useMemo(() => ({ x: TABLE_TOTAL_WIDTH }), [])

  return (
    <>
      <Table
        className="sample-table"
        title={tableTitle}
        columns={columns}
        dataSource={mergedResults}
        rowKey={rowKeyOf}
        expandable={expandable}
        pagination={false}
        size="small"
        rowClassName={rowClassName}
        scroll={scroll}
        onRow={(record) => ({
          onClick: () => {
            setExpandedRowKeys(prev => {
              const key = rowKeyOf(record)
              if (prev.includes(key)) {
                return prev.filter(k => k !== key)
              } else {
                return [...prev, key]
              }
            })
          },
          style: { cursor: 'pointer' },
        })}
      />

      <AestheticsDetailModal
        visible={aestheticsDetailVisible}
        onClose={closeAestheticsDetail}
        record={currentAestheticsRecord}
        trace={aestheticsTrace}
        onPreviewImage={openLightbox}
      />

      {/* 美观度截图灯箱 */}
      <Drawer
        open={lightboxVisible}
        onClose={closeLightbox}
        width="100%"
        className="lightbox-drawer"
        styles={{
          body: {
            padding: 0,
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            background: 'rgba(0,0,0,0.85)',
            minHeight: '100vh',
          },
        }}
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

      <BackendDetailModal
        visible={backendDetailVisible}
        onClose={closeBackendDetail}
        record={currentBackendRecord}
      />
    </>
  )
}
