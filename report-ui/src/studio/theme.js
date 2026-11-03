/**
 * 主题配置 - 集中管理所有颜色值与样式常量
 * 从 App.jsx 提取的硬编码颜色值，UI 呈现完全不变
 */

// ─── 基础色板 ────────────────────────────────────────
export const colors = {
  // 品牌色
  primary: '#2563EB',
  primaryDark: '#1D4ED8',

  // 语义色
  success: '#22C55E',
  warning: '#F59E0B',
  error: '#EF4444',
  info: '#2563EB',

  // 中性色 - 文本
  textPrimary: '#0F172A',
  textSecondary: '#475569',
  textTertiary: '#94A3B8',
  textMuted: '#64748B',
  textWhite: 'white',

  // 中性色 - 背景
  bgLayout: '#F8FAFC',
  bgWhite: '#FFFFFF',
  bgHeader: '#0F172A',
  bgContentDatasets: '#fff',

  // 中性色 - 边框
  border: '#E2E8F0',
  borderSecondary: '#F1F5F9',

  // Segmented 组件
  segmentedTrackBg: '#F1F5F9',
  segmentedItemHoverBg: '#E2E8F0',
  segmentedItemSelectedBg: '#FFFFFF',
}

// ─── 阴影 ────────────────────────────────────────
export const shadows = {
  segmentedBoxShadow: '0 1px 2px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(15, 23, 42, 0.08)',
}

// ─── 圆角 ────────────────────────────────────────
export const radii = {
  default: 8,
}

// ─── Ant Design ConfigProvider 主题 Token ──────────
export const antThemeToken = {
  colorPrimary: colors.primary,
  colorSuccess: colors.success,
  colorWarning: colors.warning,
  colorError: colors.error,
  colorInfo: colors.info,
  colorBgLayout: colors.bgLayout,
  colorText: colors.textPrimary,
  colorTextSecondary: colors.textSecondary,
  colorTextTertiary: colors.textTertiary,
  colorBorder: colors.border,
  colorBorderSecondary: colors.borderSecondary,
  borderRadius: radii.default,
  wireframe: false,
}

// ─── Ant Design Segmented 组件主题 ─────────────────
export const antSegmentedTheme = {
  trackBg: colors.segmentedTrackBg,
  trackPadding: 3,
  itemColor: colors.textMuted,
  itemHoverColor: colors.textPrimary,
  itemHoverBg: colors.segmentedItemHoverBg,
  itemSelectedBg: colors.segmentedItemSelectedBg,
  itemSelectedColor: colors.primaryDark,
  boxShadowTertiary: shadows.segmentedBoxShadow,
}

// ─── 布局样式 ──────────────────────────────────────
export const layoutStyles = {
  // 左侧侧边栏：深色、fixed 固定于视口左侧（sticky 在部分页面的
  // overflow/高度链下会失效跟随滚动），滚动交给内部菜单区
  sider: {
    background: colors.bgHeader,
    position: 'fixed',
    left: 0,
    top: 0,
    bottom: 0,
    height: '100vh',
    zIndex: 100,
    overflow: 'hidden',
    borderRight: '1px solid rgba(255, 255, 255, 0.06)',
  },
  // 菜单滚动区：扣除 Logo 高度后撑满剩余空间，菜单超高时仅侧边栏内部滚动
  siderMenuScroll: {
    height: 'calc(100% - 64px)',
    overflowY: 'auto',
    overflowX: 'hidden',
  },
  // 侧边栏顶部 Logo 区：高 64px，垂直居中
  siderLogo: {
    height: '64px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    background: colors.bgHeader,
  },
  logo: {
    color: colors.textWhite,
    fontSize: '20px',
    fontWeight: 'bold',
    marginRight: '40px',
  },
  menuTransparent: {
    background: 'transparent',
  },
  menuFlex: {
    flex: 1,
    minWidth: 0,
    background: 'transparent',
  },
  contentDefault: {
    padding: '24px',
    background: colors.bgLayout,
  },
  contentReport: {
    padding: '0',
    background: colors.bgLayout,
  },
  contentDatasets: {
    padding: '0',
    background: colors.bgContentDatasets,
  },
  contentCompare: {
    padding: '0',
    background: colors.bgLayout,
  },
}
