import React from 'react'
import { VERSION_DISPLAY } from '../constants/dataset'
import './VersionSwitcher.css'

/**
 * 胶囊式版本切换器
 * @param {string} value - 当前选中版本值
 * @param {function} onChange - 切换回调
 * @param {string[]} versions - 可选版本列表（如 ['V1', 'V1plus', 'V2']）
 */
export default function VersionSwitcher({ value, onChange, versions }) {
  const options = versions.map(v => ({ label: VERSION_DISPLAY[v] || v, value: v }))

  return (
    <div className="version-switcher">
      <span className="version-label">版本:</span>
      <div className="version-pills">
        {options.map(opt => (
          <button
            key={opt.value}
            type="button"
            className={`version-pill${value === opt.value ? ' active' : ''}`}
            onClick={() => onChange(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}
