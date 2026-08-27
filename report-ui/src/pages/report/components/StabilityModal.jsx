import React from 'react'
import { Modal, Table, Tag, Empty, Space, Divider } from 'antd'

export default function StabilityModal({ visible, onClose, record }) {
  if (!record) return null

  const { sample_id, platform } = record
  const detail = record.stability_detail || {}
  const crashEvents = detail.crash_events || []
  const anrEvents = detail.anr_events || []
  const allEvents = [
    ...crashEvents.map(e => ({ ...e, type: 'crash' })),
    ...anrEvents.map(e => ({ ...e, type: 'anr' })),
  ]

  const whiteScreenCount = detail.white_screen_count || 0
  const whiteScreenEvidence = detail.white_screen_evidence || []

  const hasEvents = allEvents.length > 0
  const hasWhiteScreen = whiteScreenCount > 0

  const columns = [
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 100,
      render: (type) => (
        <Tag color={type === 'crash' ? 'red' : 'orange'}>
          {type === 'crash' ? '崩溃' : 'ANR'}
        </Tag>
      ),
    },
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 180,
      render: (ts) => ts || '-',
    },
    {
      title: '进程',
      dataIndex: 'process',
      key: 'process',
      width: 150,
      render: (p) => p || '-',
    },
    {
      title: '详情',
      dataIndex: 'details',
      key: 'details',
      render: (d) => {
        if (!d) return '-'
        const text = typeof d === 'string' ? d : JSON.stringify(d)
        const truncated = text.length > 200 ? text.slice(0, 200) + '...' : text
        return <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: '12px' }}>{truncated}</pre>
      },
    },
  ]

  return (
    <Modal
      title={`稳定性详情 - ${sample_id} (${platform})`}
      open={visible}
      onCancel={onClose}
      footer={null}
      width={900}
      destroyOnClose
    >
      {hasEvents ? (
        <>
          <Table
            dataSource={allEvents}
            columns={columns}
            rowKey={(record, index) => `${record.type}-${index}`}
            size="small"
            pagination={false}
          />
          <div style={{ marginTop: '16px', textAlign: 'right' }}>
            <Space size="large">
              <span>
                崩溃率: <Tag color="red">{detail.crash_rate ?? 0}%</Tag>
              </span>
              <span>
                ANR率: <Tag color="orange">{detail.anr_rate ?? 0}%</Tag>
              </span>
              <span>
                白屏次数: <Tag color="purple">{whiteScreenCount}</Tag>
              </span>
            </Space>
          </div>
        </>
      ) : (
        <Empty description={
          <span style={{ color: '#52c41a', fontSize: '16px' }}>
            ✓ 无崩溃/ANR事件
          </span>
        } />
      )}
      <Divider orientation="left">白屏检测</Divider>
      {hasWhiteScreen ? (
        <Table
          dataSource={whiteScreenEvidence.map((id, index) => ({ key: index, index: index + 1, caseId: id }))}
          columns={[
            { title: '序号', dataIndex: 'index', key: 'index', width: 80 },
            { title: '测试用例 ID', dataIndex: 'caseId', key: 'caseId' },
          ]}
          size="small"
          pagination={false}
        />
      ) : (
        <Tag color="success">未检测到白屏</Tag>
      )}
    </Modal>
  )
}
