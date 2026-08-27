import React, { useState } from 'react'
import { Card, Statistic, Button, Modal, Table, Row, Col, Space, Tooltip } from 'antd'
import { WarningOutlined, TeamOutlined } from '@ant-design/icons'

export default function ExecutionOverview({ executionOverview, sampleTitleMap = {} }) {
  const [error429ModalVisible, setError429ModalVisible] = useState(false)
  const [subAgentsModalVisible, setSubAgentsModalVisible] = useState(false)
  const [reviewIssuesModalVisible, setReviewIssuesModalVisible] = useState(false)

  if (!executionOverview) return null

  const { error_429, sub_agents, review_issues } = executionOverview

  const formatSampleName = (record) => {
    if (record.title && record.title !== record.sample_id) {
      return record.title
    }
    // details 里无标题时用样本集清单标题兜底，仍无才回退 sample_id
    if (sampleTitleMap[record.sample_id]) {
      return sampleTitleMap[record.sample_id]
    }
    return record.sample_id
  }

  // 429 错误详情表格列
  const error429Columns = [
    {
      title: '样本名称',
      key: 'name',
      render: (_, record) => formatSampleName(record),
    },
    {
      title: '错误次数',
      dataIndex: 'count',
      key: 'count',
      sorter: (a, b) => a.count - b.count,
      defaultSortOrder: 'descend',
    },
  ]

  // 子 Agent 详情表格列
  const subAgentsColumns = [
    {
      title: '样本名称',
      key: 'name',
      render: (_, record) => formatSampleName(record),
    },
    {
      title: '生码Agent数',
      dataIndex: 'code_gen_count',
      key: 'code_gen_count',
    },
    {
      title: 'Review Agent数',
      dataIndex: 'review_count',
      key: 'review_count',
    },
  ]

  // Review 问题详情表格列
  const reviewIssuesColumns = [
    {
      title: '样本名称',
      dataIndex: 'title',
      key: 'title',
      render: (_, record) => formatSampleName(record),
    },
    {
      title: 'Agent',
      dataIndex: 'agent',
      key: 'agent',
    },
    {
      title: '问题类型',
      dataIndex: 'type',
      key: 'type',
    },
    {
      title: '文件',
      dataIndex: 'file',
      key: 'file',
      ellipsis: true,
      render: (text) => (
        <Tooltip title={text}>
          <span>{text}</span>
        </Tooltip>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (text) => (
        <Tooltip title={text}>
          <span>{text}</span>
        </Tooltip>
      ),
    },
    {
      title: '是否修复',
      dataIndex: 'fixed',
      key: 'fixed',
      align: 'center',
      render: (fixed) => (fixed ? '✅' : '❌'),
    },
  ]

  const error429Details = error_429?.details
    ? [...error_429.details].sort((a, b) => b.count - a.count)
    : []

  const subAgentsDetails = sub_agents?.details
    ? [...sub_agents.details].sort((a, b) => (b.code_gen_count + b.review_count) - (a.code_gen_count + a.review_count))
    : []

  const reviewIssuesDetails = review_issues?.details ?? []

  // 导出 Review 问题为 Markdown 文件
  const handleExportReviewIssues = () => {
    const escapeCell = (value) =>
      String(value ?? '')
        .replace(/\|/g, '\\|')
        .replace(/\r?\n/g, ' ')

    const totalFound = review_issues?.total_found ?? 0
    const totalFixed = review_issues?.total_fixed ?? 0
    const totalUnfixed = totalFound - totalFixed

    const lines = []
    lines.push('# Review 问题汇总')
    lines.push('')
    lines.push(`**统计**: ${totalFound} 发现 / ${totalFixed} 修复 / ${totalUnfixed} 未修复`)
    lines.push('')
    lines.push('## 问题列表')
    lines.push('')
    lines.push('| 样本 | Agent | 类型 | 文件 | 描述 | 修复 |')
    lines.push('|------|-------|------|------|------|------|')
    reviewIssuesDetails.forEach((item) => {
      lines.push(
        `| ${escapeCell(formatSampleName(item))} | ${escapeCell(item.agent)} | ${escapeCell(item.type)} | ${escapeCell(item.file)} | ${escapeCell(item.description)} | ${item.fixed ? '✅' : '❌'} |`
      )
    })

    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'review_issues_summary.md'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <Card
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ display: 'inline-block', width: 4, height: 18, borderRadius: 2, background: '#6366f1' }} />
            <span style={{ fontSize: 16, fontWeight: 700, color: '#1f2937' }}>执行概览</span>
          </div>
        }
        size="small"
      >
        <Row gutter={[32, 16]}>
          {/* 429 错误统计 */}
          <Col xs={24} md={12}>
            <div style={{ marginBottom: 8 }}>
              <Space size="large">
                <Statistic
                  title="429错误总次数"
                  value={error_429?.total_count ?? 0}
                  prefix={<WarningOutlined style={{ color: '#faad14' }} />}
                />
                <Statistic
                  title="受影响样本"
                  value={`${error_429?.affected_samples ?? 0} / ${error_429?.total_samples ?? 0}`}
                />
              </Space>
            </div>
            {error_429?.details?.length > 0 && (
              <Button type="link" style={{ paddingLeft: 0 }} onClick={() => setError429ModalVisible(true)}>
                查看详情
              </Button>
            )}
          </Col>

          {/* 子 Agent 个数统计 */}
          <Col xs={24} md={12}>
            <Row gutter={[24, 8]}>
              {/* 生码Agent总数 + 查看详情 */}
              <Col>
                <Statistic
                  title="生码Agent总数"
                  value={sub_agents?.total_code_gen ?? 0}
                  prefix={<TeamOutlined style={{ color: '#6366f1' }} />}
                />
                {sub_agents?.details?.length > 0 && (
                  <Button type="link" style={{ paddingLeft: 0 }} onClick={() => setSubAgentsModalVisible(true)}>
                    查看详情
                  </Button>
                )}
              </Col>

              {/* Review Agent总数（无按钮） */}
              <Col>
                <Statistic
                  title="Review Agent总数"
                  value={sub_agents?.total_review ?? 0}
                />
              </Col>

              {/* Review问题 + Review问题详情 */}
              <Col>
                <Statistic
                  title="Review问题"
                  value={`${review_issues?.total_found ?? 0} 发现 / ${review_issues?.total_fixed ?? 0} 修复`}
                />
                {review_issues?.details?.length > 0 && (
                  <Button type="link" style={{ paddingLeft: 0 }} onClick={() => setReviewIssuesModalVisible(true)}>
                    Review问题详情
                  </Button>
                )}
              </Col>
            </Row>
          </Col>
        </Row>
      </Card>

      {/* 429 错误详情 Modal */}
      <Modal
        title="429错误详情"
        open={error429ModalVisible}
        onCancel={() => setError429ModalVisible(false)}
        footer={null}
        width={520}
      >
        <Table
          columns={error429Columns}
          dataSource={error429Details}
          rowKey="sample_id"
          pagination={false}
          scroll={{ y: 400 }}
          size="small"
        />
      </Modal>

      {/* 子 Agent 详情 Modal */}
      <Modal
        title="子Agent个数详情"
        open={subAgentsModalVisible}
        onCancel={() => setSubAgentsModalVisible(false)}
        footer={null}
        width={600}
      >
        <Table
          columns={subAgentsColumns}
          dataSource={subAgentsDetails}
          rowKey="sample_id"
          pagination={false}
          scroll={{ y: 400 }}
          size="small"
        />
      </Modal>

      {/* Review 问题详情 Modal */}
      <Modal
        title="Review问题详情"
        open={reviewIssuesModalVisible}
        onCancel={() => setReviewIssuesModalVisible(false)}
        footer={
          <Button onClick={handleExportReviewIssues}>
            导出MD
          </Button>
        }
        width={960}
      >
        <Table
          columns={reviewIssuesColumns}
          dataSource={reviewIssuesDetails}
          rowKey={(record, index) => `${record.sample_id}-${record.agent}-${index}`}
          pagination={false}
          scroll={{ y: 400 }}
          size="small"
        />
      </Modal>
    </>
  )
}
