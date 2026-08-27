import React, { useState } from 'react'
import { Table, Button, Tag, Row, Col } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { QualityRuleModal, ExperienceRuleModal } from './RuleModals'
import { formatDuration } from '../utils'

function formatScore(v) {
  if (v === undefined || v === null) return '-'
  const n = Number(v)
  if (!Number.isFinite(n)) return '-'
  return n.toFixed(1)
}

export default function PlatformTable({ perPlatform }) {
  const [qualityModalVisible, setQualityModalVisible] = useState(false)
  const [experienceModalVisible, setExperienceModalVisible] = useState(false)

  if (!perPlatform) return null

  const dataSource = Object.entries(perPlatform).map(([platform, data]) => ({
    platform,
    ...data,
    key: platform,
  }))

  const columns = [
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      render: (platform) => <Tag color="blue">{platform}</Tag>,
    },
    {
      title: '样本数',
      dataIndex: 'sample_count',
      key: 'sample_count',
    },
    {
      title: '成功率',
      dataIndex: 'mean_success_rate',
      key: 'mean_success_rate',
      render: (v) => `${formatScore(v)}%`,
    },
    {
      title: '功能完整性',
      dataIndex: 'mean_quality',
      key: 'mean_quality',
      render: (v) => `${formatScore(v)}分`,
    },
    {
      title: '体验',
      dataIndex: 'mean_experience',
      key: 'mean_experience',
      render: (v) => `${formatScore(v)}分`,
    },
  ]

  const expandedRowRender = (record) => {
    const e2ePass = typeof record.e2e_pass === 'number' ? record.e2e_pass : 0
    const e2eCount = typeof record.e2e_count === 'number' ? record.e2e_count : 0
    const e2ePassRate = e2eCount > 0 ? ((e2ePass / e2eCount) * 100).toFixed(1) : '-'

    return (
      <div className="detail-grid">
        <Row gutter={[16, 16]}>
          <Col xs={24} md={8}>
            <div className="detail-section">
              <div className="detail-section-title">成功率详情</div>
              <div className="detail-item">
                <span className="detail-label">平均首次生成成功率</span>
                <span className="detail-value">{formatScore(record.mean_initial_generation_rate)}%</span>
              </div>
            </div>
          </Col>
          <Col xs={24} md={8}>
            <div className="detail-section">
              <div className="detail-section-title">
                功能完整性详情
                <Button
                  type="link"
                  size="small"
                  icon={<InfoCircleOutlined />}
                  onClick={() => setQualityModalVisible(true)}
                >
                  评分规则
                </Button>
              </div>
              <div className="detail-item">
                <span className="detail-label">用例完整性(E2E通过率)</span>
                <span className="detail-value">{e2ePassRate === '-' ? '-' : `${e2ePassRate}%`}</span>
              </div>
              <div className="detail-item">
                <span className="detail-label">运行稳定性</span>
                <span className="detail-value">
                  <Tag color={record.total_crashes > 0 ? 'error' : 'success'}>
                    崩溃 {record.total_crashes ?? 0}
                  </Tag>
                  <Tag color={record.total_anrs > 0 ? 'warning' : 'success'}>
                    ANR {record.total_anrs ?? 0}
                  </Tag>
                  <Tag color={record.total_white_screens > 0 ? 'warning' : 'success'}>
                    白屏 {record.total_white_screens ?? 0}
                  </Tag>
                </span>
              </div>
              <div className="detail-item">
                <span className="detail-label">后端完整性</span>
                <span className="detail-value">
                  {(record.mean_backend_completeness === null || record.mean_backend_completeness === undefined)
                    ? 'N/A'
                    : `${formatScore(record.mean_backend_completeness)}分`}
                </span>
              </div>
            </div>
          </Col>
          <Col xs={24} md={8}>
            <div className="detail-section">
              <div className="detail-section-title">
                体验详情
                <Button
                  type="link"
                  size="small"
                  icon={<InfoCircleOutlined />}
                  onClick={() => setExperienceModalVisible(true)}
                >
                  评分规则
                </Button>
              </div>
              <div className="detail-item">
                <span className="detail-label">平均耗时</span>
                <span className="detail-value">{formatDuration(record.mean_duration_ms)}</span>
              </div>
              {/* Token/花费仅部分生成器提供，拿不到数据时整行隐藏，不对外展示占位符 */}
              {(record.mean_token_total || 0) > 0 && (
                <div className="detail-item">
                  <span className="detail-label">Token消耗</span>
                  <span className="detail-value">
                    输入 {record.mean_token_input != null ? Math.round(record.mean_token_input).toLocaleString('zh-CN') : '-'} / 输出 {record.mean_token_output != null ? Math.round(record.mean_token_output).toLocaleString('zh-CN') : '-'} / 总计 {Math.round(record.mean_token_total).toLocaleString('zh-CN')}
                  </span>
                </div>
              )}
              {record.mean_cost_usd != null && record.mean_cost_usd > 0 && (
                <div className="detail-item">
                  <span className="detail-label">平均花费</span>
                  <span className="detail-value">${record.mean_cost_usd.toFixed(4)}</span>
                </div>
              )}
              <div className="detail-item">
                <span className="detail-label">UI美观度</span>
                <span className="detail-value">
                  {(record.mean_aesthetics_score === null || record.mean_aesthetics_score === undefined || record.mean_aesthetics_score === 0)
                    ? '-'
                    : `${formatScore(record.mean_aesthetics_score)} / 10`}
                </span>
              </div>
            </div>
          </Col>
        </Row>
      </div>
    )
  }

  return (
    <>
      <Table
        title={() => (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ display: 'inline-block', width: 4, height: 18, borderRadius: 2, background: '#6366f1' }} />
                  <span style={{ fontSize: 16, fontWeight: 700, color: '#1f2937' }}>平台汇总</span>
                </div>
              )}
        columns={columns}
        dataSource={dataSource}
        rowKey="platform"
        expandable={{ expandedRowRender, defaultExpandAllRows: true }}
        pagination={false}
        size="small"
      />
      <QualityRuleModal visible={qualityModalVisible} onClose={() => setQualityModalVisible(false)} />
      <ExperienceRuleModal visible={experienceModalVisible} onClose={() => setExperienceModalVisible(false)} />
    </>
  )
}
