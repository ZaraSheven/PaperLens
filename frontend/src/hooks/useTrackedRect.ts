import { useEffect, useState } from 'react'

/**
 * 持续跟踪某个元素在视口里的位置。滚动捕获阶段监听，页面内任意滚动容器都能覆盖。
 * 所有更新都收进 requestAnimationFrame，避免滚动时反复触发布局计算。
 *
 * revision 用于「元素自己被重排但既没滚动也没改窗口大小」的情况，典型场景是 PDF 缩放：
 * 页面尺寸变了、锚点位置跟着变，但不会触发 scroll 或 resize。缩放值时把它传进来即可。
 */
export function useTrackedRect(element: Element | null, revision?: unknown): DOMRect | null {
  const [rect, setRect] = useState<DOMRect | null>(null)

  useEffect(() => {
    if (!element) {
      setRect(null)
      return
    }

    let frame = 0
    const update = () => {
      frame = 0
      setRect(element.getBoundingClientRect())
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update)
    }

    update()
    window.addEventListener('scroll', schedule, true)
    window.addEventListener('resize', schedule)
    return () => {
      if (frame) cancelAnimationFrame(frame)
      window.removeEventListener('scroll', schedule, true)
      window.removeEventListener('resize', schedule)
    }
  }, [element, revision])

  return rect
}

/** 按选择器取元素，供气泡找到段落和标记的 DOM 节点。 */
export function useQueriedElement(selector: string | null): Element | null {
  const [element, setElement] = useState<Element | null>(null)

  useEffect(() => {
    setElement(selector ? document.querySelector(selector) : null)
  }, [selector])

  return element
}

