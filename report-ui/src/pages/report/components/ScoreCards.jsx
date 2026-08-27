import React from 'react'
import { Card, Row, Col, Tooltip } from 'antd'
import { CheckCircleOutlined, StarOutlined, SmileOutlined, DollarOutlined, QuestionCircleOutlined } from '@ant-design/icons'

// 安全格式化数字：NaN/Infinity/非数字一律返回 '-'
function safeFormatNumber(value, decimals = 1) {
  if (typeof value !== 'number' || isNaN(value) || !isFinite(value)) {
    return '-'
  }
  return value.toFixed(decimals)
}

export default function ScoreCards({ summary }) {
  if (!summary) return null

  const { mean_success_rate, mean_quality, mean_experience, mean_cost_usd } = summary

  const cards = [
    {
      title: '成功率',
      value: mean_success_rate ?? 0,
      suffix: '%',
      icon: <CheckCircleOutlined />,
      iconColor: '#52c41a',
      valueGradient: 'linear-gradient(135deg, #34d399 0%, #10b981 100%)',
      ruleAnchor: 'success-detail',
    },
    {
      title: '功能完整性分',
      value: mean_quality ?? 0,
      suffix: '分',
      icon: <StarOutlined />,
      iconColor: '#1890ff',
      valueGradient: 'linear-gradient(135deg, #60a5fa 0%, #2563eb 100%)',
      ruleAnchor: 'quality-detail',
    },
    {
      title: '体验分',
      value: mean_experience ?? 0,
      suffix: '分',
      icon: <SmileOutlined />,
      iconColor: '#764ba2',
      valueGradient: 'linear-gradient(135deg, #a78bfa 0%, #7c3aed 100%)',
      ruleAnchor: 'experience-detail',
    },
  ]

  // 平均成本卡片（美元）：仅当 mean_cost_usd 有效且大于 0 时才添加
  if (mean_cost_usd != null && mean_cost_usd > 0) {
    cards.push({
      title: '平均成本',
      value: mean_cost_usd,
      prefix: '$',
      decimals: 4,
      icon: <DollarOutlined />,
      iconColor: '#faad14',
      valueGradient: 'linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%)',
    })
  }

  return (
    <div className="score-cards">
      <Row gutter={[16, 16]}>
        {cards.map(card => (
          <Col xs={24} sm={6} key={card.title}>
            <Card
              className="score-card-item"
              style={{ background: '#fff', borderRadius: '16px' }}
              styles={{ body: { padding: '24px' } }}
            >
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: '16px' }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '36px',
                    height: '36px',
                    borderRadius: '10px',
                    background: `${card.iconColor}15`,
                    color: card.iconColor,
                    fontSize: '18px',
                    marginRight: '12px',
                  }}
                >
                  {card.icon}
                </span>
                <span style={{ color: '#6c757d', fontSize: '14px', fontWeight: 500 }}>
                  {card.title}
                </span>
                {card.ruleAnchor && (
                  <Tooltip title="查看评分规则">
                    <a
                      href={`/scoring-rules#${card.ruleAnchor}`}
                      target="_blank"
                      rel="noreferrer"
                      style={{ marginLeft: 6, color: '#bfbfbf', display: 'inline-flex' }}
                      aria-label={`查看${card.title}评分规则`}
                    >
                      <QuestionCircleOutlined />
                    </a>
                  </Tooltip>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px' }}>
                {card.prefix && (
                  <span
                    className="score-card-value"
                    style={{
                      fontSize: '42px',
                      fontWeight: 700,
                      lineHeight: 1.2,
                      background: card.valueGradient || 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                      WebkitBackgroundClip: 'text',
                      WebkitTextFillColor: 'transparent',
                    }}
                  >
                    {card.prefix}
                  </span>
                )}
                <span
                  className="score-card-value"
                  style={{
                    fontSize: '42px',
                    fontWeight: 700,
                    lineHeight: 1.2,
                    background: card.valueGradient || 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                    WebkitBackgroundClip: 'text',
                    WebkitTextFillColor: 'transparent',
                  }}
                >
                  {safeFormatNumber(card.value, card.decimals ?? 1)}
                </span>
                <span style={{ color: '#6c757d', fontSize: '14px', fontWeight: 500 }}>
                  {card.suffix}
                </span>
              </div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}
