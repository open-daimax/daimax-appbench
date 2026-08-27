import React from 'react'
import ReactDOM from 'react-dom/client'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import ReportView from '../pages/report'
import { getWorkspaceId } from '../data/local'
import '../index.css'

/**
 * 本地单文件报告入口（CLI 导出 report.html 专用）
 *
 * - 只挂载评测报告页（ReportView），无其他路由
 * - 使用 MemoryRouter：file:// 协议下无服务端路由，初始地址由注入数据决定
 * - 报告数据来自 window.__REPORT_DATA__（见 data/local.js）
 */
const wsId = getWorkspaceId()

document.title = `评测报告 - ${wsId}`

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN}>
      <MemoryRouter initialEntries={[`/report/${wsId}`]}>
        <Routes>
          <Route path="/report/:wsId" element={<ReportView />} />
        </Routes>
      </MemoryRouter>
    </ConfigProvider>
  </React.StrictMode>,
)
