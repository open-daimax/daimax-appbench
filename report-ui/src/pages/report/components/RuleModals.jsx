import React from 'react'
import { Modal, Table, Typography } from 'antd'

const { Title, Paragraph } = Typography

export function QualityRuleModal({ visible, onClose }) {
  const columns = [
    { title: '维度', dataIndex: 'dimension', key: 'dimension' },
    { title: '作用', dataIndex: 'role', key: 'role' },
    { title: '扣分系数', dataIndex: 'coefficient', key: 'coefficient' },
    { title: '说明', dataIndex: 'desc', key: 'desc' },
  ]

  const data = [
    { dimension: '用例完整性', role: '基础分', coefficient: '—', desc: 'E2E 测试通过率 × 100，作为计算基准' },
    { dimension: '运行稳定性', role: '扣分项', coefficient: '0.2（最多扣20%）', desc: '基于崩溃/ANR/白屏问题率；缺失时不扣分' },
    { dimension: '后端完整性', role: '扣分项', coefficient: '0.3（最多扣30%）', desc: '仅 requires_backend=true 生效；缺失时不扣分' },
  ]

  const stabilityColumns = [
    { title: '问题率', dataIndex: 'range', key: 'range' },
    { title: '得分区间', dataIndex: 'score', key: 'score' },
  ]

  const stabilityData = [
    { range: '0%', score: '100 分（完美稳定）' },
    { range: '≤5%', score: '80~100 分' },
    { range: '5%~15%', score: '55~90 分' },
    { range: '15%~30%', score: '30~70 分' },
    { range: '>30%', score: '0~40 分' },
  ]

  return (
    <Modal
      title="功能完整性评分规则"
      open={visible}
      onCancel={onClose}
      footer={null}
      width={760}
      destroyOnClose
    >
      <Paragraph>
        <strong>计算公式：</strong>功能完整性 = 用例完整性 - 稳定性扣分 - 后端扣分
      </Paragraph>
      <Paragraph>
        <strong>扣分规则：</strong>稳定性扣分 = (1 - 稳定性分/100) × 基础分 × 0.2；后端扣分 = (1 - 后端完整性分/100) × 基础分 × 0.3（仅需后端时）。缺失项不扣分，结果最低为0。
      </Paragraph>
      <Title level={5}>维度与扣分规则</Title>
      <Table dataSource={data} columns={columns} pagination={false} size="small" rowKey="dimension" />
      <Title level={5} style={{ marginTop: '16px' }}>稳定性问题率分段</Title>
      <Table dataSource={stabilityData} columns={stabilityColumns} pagination={false} size="small" rowKey="range" />
      <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
        构建 / 安装 / 启动失败时，用例完整性与稳定性强制为 0；后端完整性同样置 0（仅 requires_backend 样本）。
      </Paragraph>
      <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
        <a href="/scoring-rules#quality-detail" target="_blank" rel="noreferrer">查看完整评分规则 →</a>
      </Paragraph>
    </Modal>
  )
}

export function ExperienceRuleModal({ visible, onClose }) {
  const thresholdColumns = [
    { title: '耗时范围', dataIndex: 'range', key: 'range' },
    { title: '评分规则', dataIndex: 'rule', key: 'rule' },
  ]

  const thresholdData = [
    { range: '≤ 2分钟', rule: '100分' },
    { range: '2分钟 ~ 30分钟', rule: '线性递减：100分 → 5分' },
    { range: '30分钟 ~ 60分钟', rule: '线性递减：5分 → 0分' },
    { range: '> 60分钟', rule: '0分' },
  ]

  const exampleColumns = [
    { title: '耗时', dataIndex: 'duration', key: 'duration' },
    { title: '对应得分', dataIndex: 'score', key: 'score' },
  ]

  const exampleData = [
    { duration: '1分钟', score: '100分' },
    { duration: '10分钟', score: '~70分' },
    { duration: '30分钟', score: '5分' },
    { duration: '45分钟', score: '~2.5分' },
    { duration: '60分钟', score: '0分' },
  ]

  return (
    <Modal
      title="体验评分规则"
      open={visible}
      onCancel={onClose}
      footer={null}
      width={700}
      destroyOnClose
    >
      <Paragraph>
        <strong>体验分</strong>主要基于端到端生成耗时进行评分，同时参考包大小和UI美观度。权重组成：耗时60% + 包大小20% + 美观度20%（缺失时动态归一化）。
      </Paragraph>
      <Title level={5}>耗时评分阈值表</Title>
      <Table dataSource={thresholdData} columns={thresholdColumns} pagination={false} size="small" rowKey="range" />
      <Title level={5} style={{ marginTop: '16px' }}>评分示例</Title>
      <Table dataSource={exampleData} columns={exampleColumns} pagination={false} size="small" rowKey="duration" />
      {/* UI美观度规则 */}
      <div style={{ marginTop: 16 }}>
        <strong>UI美观度（权重 20%）</strong>
        <div style={{ marginTop: 8, color: '#555' }}>
          基于E2E测试过程截图，由AI视觉模型评估UI设计质量，0-10分（转换为0-100分参与体验综合分）
        </div>
        <table style={{ width: '100%', marginTop: 8, borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', padding: '4px 8px', background: '#f5f5f5' }}>评分</th>
              <th style={{ textAlign: 'left', padding: '4px 8px', background: '#f5f5f5' }}>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr><td style={{ padding: '4px 8px' }}>9-10</td><td style={{ padding: '4px 8px' }}>优秀 - 接近商业水准</td></tr>
            <tr><td style={{ padding: '4px 8px' }}>7-9</td><td style={{ padding: '4px 8px' }}>良好 - 较专业</td></tr>
            <tr><td style={{ padding: '4px 8px' }}>5-7</td><td style={{ padding: '4px 8px' }}>中等 - 基本可用</td></tr>
            <tr><td style={{ padding: '4px 8px' }}>3-5</td><td style={{ padding: '4px 8px' }}>一般 - 有明显瑕疵</td></tr>
            <tr><td style={{ padding: '4px 8px' }}>0-3</td><td style={{ padding: '4px 8px' }}>差 - 明显不专业</td></tr>
          </tbody>
        </table>
        <div style={{ marginTop: 8, color: '#888', fontSize: 12 }}>
          评分依据：配色协调性(25%)、布局规整度(25%)、视觉层次(20%)、字体规范性(15%)、整体专业感(15%)
        </div>
        <div style={{ marginTop: 4, color: '#888', fontSize: 12 }}>
          如无截图数据，美观度不参与体验综合分计算。
        </div>
      </div>
      <Paragraph style={{ marginTop: 16, marginBottom: 0 }}>
        <a href="/scoring-rules#experience-detail" target="_blank" rel="noreferrer">查看完整评分规则 →</a>
      </Paragraph>
    </Modal>
  )
}
