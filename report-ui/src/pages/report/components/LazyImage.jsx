import React, { useEffect, useRef, useState } from 'react'
import { Image } from 'antd'

/**
 * LazyImage —— 视口懒加载图片组件
 *
 * 优化策略：
 * 1) 通过 IntersectionObserver 监听元素是否进入视口；未进入时仅渲染骨架占位，
 *    避免 100+ 行数据下同时挂载大量 <img>/<Image> 引发的内存与解码压力。
 * 2) 一旦进入过视口即停止观察并永久标记可见，避免快速滚动时反复挂卸；
 *    浏览器自身会缓存已加载的图片，重新进入视口时从缓存读取。
 * 3) 浏览器不支持 IntersectionObserver 时降级为立即加载，保证功能完整性。
 *
 * 注意：此组件仅控制"何时开始加载"，真正的网络请求仍由浏览器调度；
 * 失败回退由 antd <Image> 内部 fallback 处理。
 */
function LazyImage({
  src,
  alt,
  width = 120,
  height,
  fallback,
  rootMargin = '200px',
  placeholderText = '加载中…',
  imgProps,
  ...rest
}) {
  const containerRef = useRef(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (visible) return
    const el = containerRef.current
    if (!el) return

    // 浏览器不支持 IntersectionObserver 时立刻加载
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true)
      return
    }

    // 兜底：若 IntersectionObserver 在 2s 内未触发（如展开区域/表格内场景），强制加载
    let timer = setTimeout(() => {
      setVisible(true)
    }, 2000)

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisible(true)
            observer.disconnect()
            clearTimeout(timer)
            break
          }
        }
      },
      { rootMargin }
    )
    observer.observe(el)
    return () => {
      observer.disconnect()
      clearTimeout(timer)
    }
  }, [visible, rootMargin])

  const placeholderHeight = height ?? 160

  return (
    <div
      ref={containerRef}
      style={{
        display: 'inline-block',
        width,
        minHeight: placeholderHeight,
        ...(rest.style || {}),
      }}
    >
      {visible ? (
        <Image
          src={src}
          alt={alt}
          width={width}
          loading="lazy"
          fallback={fallback}
          placeholder
          {...imgProps}
        />
      ) : (
        <div
          aria-label={alt}
          style={{
            width,
            height: placeholderHeight,
            background: '#f5f5f5',
            border: '1px solid #e8e8e8',
            borderRadius: 4,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#bbb',
            fontSize: 11,
          }}
        >
          {placeholderText}
        </div>
      )}
    </div>
  )
}

// 使用 React.memo：父组件每次渲染传入的 src/alt 多为稳定字符串，
// 无谓的重渲染将被 memo 拦截，进一步降低虚拟滚动滚动时的渲染成本。
export default React.memo(LazyImage)
