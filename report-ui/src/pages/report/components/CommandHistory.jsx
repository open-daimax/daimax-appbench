import React, { useState, useMemo } from 'react'
import {
  List, Tag, Select, Pagination, Empty, Typography, Space,
  Collapse, Button, Tooltip
} from 'antd'
import {
  DownOutlined,
  UpOutlined,
  ClockCircleOutlined,
  LoadingOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  FieldTimeOutlined,
  CodeOutlined
} from '@ant-design/icons'
import { getCommandHistory } from '../../../data/local'

const { Text } = Typography
const { Panel } = Collapse

const COMMAND_TYPE_MAP = {
  generate: { text: '生成', color: 'blue' },
  generate_and_test: { text: '生成并评测', color: 'geekblue' },
  evaluate: { text: '评测', color: 'orange' },
  report: { text: '报告', color: 'green' },
  retest: { text: '重测', color: 'purple' }
}

const STATUS_CONFIG = {
  running: { color: 'processing', text: '执行中', icon: <LoadingOutlined spin /> },
  completed: { color: 'success', text: '已完成', icon: <CheckCircleOutlined /> },
  failed: { color: 'error', text: '失败', icon: <CloseCircleOutlined /> }
}

function formatDuration(ms) {
  if (!ms || ms < 0) return '-'
  const seconds = Math.floor(ms / 1000)
  if (seconds < 60) return `${seconds}秒`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) {
    return `${minutes}分${seconds % 60}秒`
  }
  const hours = Math.floor(minutes / 60)
  return `${hours}小时${minutes % 60}分${seconds % 60}秒`
}

function formatDateTime(isoString) {
  if (!isoString) return '-'
  try {
    return new Date(isoString).toLocaleString('zh-CN')
  } catch {
    return isoString
  }
}

function formatJsonPreview(obj) {
  if (!obj || Object.keys(obj).length === 0) return <Text type="secondary">无</Text>
  return (
    <pre style={{
      margin: 0,
      padding: '12px',
      background: '#F8FAFC',
      borderRadius: '6px',
      fontSize: '13px',
      lineHeight: 1.6,
      overflow: 'auto',
      maxHeight: '300px'
    }}>
      {JSON.stringify(obj, null, 2)}
    </pre>
  )
}

function CommandHistory() {
  const [filterType, setFilterType] = useState('all')
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [expandedIds, setExpandedIds] = useState(new Set())

  // 指令历史随报告注入（工作区 command_history.json），筛选与分页全在前端完成
  const allCommands = useMemo(() => getCommandHistory(), [])

  const filteredCommands = useMemo(
    () => (filterType === 'all' ? allCommands : allCommands.filter(c => c.type === filterType)),
    [allCommands, filterType]
  )

  const total = filteredCommands.length
  const commands = useMemo(
    () => filteredCommands.slice((currentPage - 1) * pageSize, currentPage * pageSize),
    [filteredCommands, currentPage, pageSize]
  )

  const toggleExpand = (commandId) => {
    if (commandId == null) return // 防止 undefined 被加入 Set 导致全部展开
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(commandId)) {
        next.delete(commandId)
      } else {
        next.add(commandId)
      }
      return next
    })
  }

  // 类型选项取自实际数据，避免列出本工作区没出现过的指令类型
  const typeOptions = useMemo(() => {
    const types = [...new Set(allCommands.map(c => c.type).filter(Boolean))]
    return [
      { value: 'all', label: '全部类型' },
      ...types.map(t => ({ value: t, label: COMMAND_TYPE_MAP[t]?.text || t })),
    ]
  }, [allCommands])

  return (
    <div>
      {/* 筛选栏 */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 16,
        flexWrap: 'wrap',
        gap: 12
      }}>
        <Space>
          <FieldTimeOutlined style={{ fontSize: 18, color: '#2563EB' }} />
          <Text strong style={{ fontSize: 16 }}>指令历史</Text>
        </Space>
        <Select
          value={filterType}
          options={typeOptions}
          onChange={(value) => {
            setFilterType(value)
            setCurrentPage(1)
          }}
          style={{ width: 140 }}
          size="middle"
        />
      </div>

      {commands.length === 0 ? (
        <Empty description="暂无指令记录" style={{ padding: 60 }} />
      ) : (
        <>
          <List
            dataSource={commands}
            renderItem={(cmd) => {
              const typeCfg = COMMAND_TYPE_MAP[cmd.type] || { text: cmd.type || '未知', color: 'default' }
              const statusCfg = STATUS_CONFIG[cmd.status] || STATUS_CONFIG.running
              const isExpanded = cmd.command_id != null && expandedIds.has(cmd.command_id)
              return (
                <List.Item
                  style={{
                    padding: '16px 0',
                    borderBottom: '1px solid #F1F5F9'
                  }}
                >
                  <div style={{ width: '100%' }}>
                    {/* 主行 */}
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        flexWrap: 'wrap',
                        gap: 12,
                        cursor: 'pointer'
                      }}
                      onClick={() => toggleExpand(cmd.command_id)}
                    >
                      <Space size={16} wrap>
                        {/* 类型标签 */}
                        <Tag color={typeCfg.color} style={{ fontSize: 13, padding: '2px 10px', margin: 0 }}>
                          {typeCfg.text}
                        </Tag>

                        {/* 时间 */}
                        <Space size={4}>
                          <ClockCircleOutlined style={{ color: '#94A3B8', fontSize: 13 }} />
                          <Text style={{ color: '#475569', fontSize: 13 }}>
                            {formatDateTime(cmd.created_at)}
                          </Text>
                        </Space>

                        {/* 状态 */}
                        <Tag color={statusCfg.color} icon={statusCfg.icon} style={{ margin: 0 }}>
                          {statusCfg.text}
                        </Tag>

                        {/* 耗时 */}
                        {cmd.duration_ms !== undefined && cmd.duration_ms !== null && (
                          <Tooltip title="执行耗时">
                            <Text style={{ color: '#64748B', fontSize: 13 }}>
                              {formatDuration(cmd.duration_ms)}
                            </Text>
                          </Tooltip>
                        )}
                      </Space>

                      {/* 展开按钮 */}
                      <Button
                        type="text"
                        size="small"
                        icon={isExpanded ? <UpOutlined /> : <DownOutlined />}
                        style={{ color: '#64748B' }}
                      >
                        {isExpanded ? '收起' : '详情'}
                      </Button>
                    </div>

                    {/* 展开详情 */}
                    {isExpanded && (
                      <div style={{ marginTop: 16 }}>
                        <Collapse
                          defaultActiveKey={['params']}
                          bordered={false}
                          style={{ background: 'transparent' }}
                        >
                          <Panel
                            header={
                              <Space>
                                <CodeOutlined style={{ color: '#2563EB' }} />
                                <Text strong>参数 (params)</Text>
                              </Space>
                            }
                            key="params"
                          >
                            {formatJsonPreview(cmd.params)}
                          </Panel>
                          <Panel
                            header={
                              <Space>
                                <CheckCircleOutlined style={{ color: '#22C55E' }} />
                                <Text strong>结果摘要 (result_summary)</Text>
                              </Space>
                            }
                            key="result_summary"
                          >
                            {formatJsonPreview(cmd.result_summary)}
                          </Panel>
                          {cmd.error && (
                            <Panel
                              header={
                                <Space>
                                  <CloseCircleOutlined style={{ color: '#EF4444' }} />
                                  <Text strong type="danger">错误信息</Text>
                                </Space>
                              }
                              key="error"
                            >
                              <pre style={{
                                margin: 0,
                                padding: '12px',
                                background: '#FEF2F2',
                                borderRadius: '6px',
                                fontSize: '13px',
                                color: '#DC2626',
                                overflow: 'auto',
                                maxHeight: '200px'
                              }}>
                                {typeof cmd.error === 'string' ? cmd.error : JSON.stringify(cmd.error, null, 2)}
                              </pre>
                            </Panel>
                          )}
                        </Collapse>
                      </div>
                    )}
                  </div>
                </List.Item>
              )
            }}
          />

          {/* 分页 */}
          {total > pageSize && (
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 24 }}>
              <Pagination
                current={currentPage}
                pageSize={pageSize}
                total={total}
                showSizeChanger
                pageSizeOptions={[10, 20, 50]}
                showTotal={(t) => `共 ${t} 条`}
                onChange={(page, size) => {
                  setCurrentPage(page)
                  if (size !== pageSize) {
                    setPageSize(size)
                  }
                }}
              />
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default CommandHistory
