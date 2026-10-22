import { useEffect, useRef, useState, type MouseEvent } from 'react'
import type { PDFDocumentProxy } from 'pdfjs-dist'

import type { Block, PageSize } from '../types'
import { errorMessage } from '../util'

interface Props {
  pdf: PDFDocumentProxy
  index: number
  size: PageSize
  scale: number
  blocks: Block[]
  openBlockId: string | null
  selectedIds: ReadonlySet<string>
  onActivate: (blockId: string, event: MouseEvent<HTMLElement>) => void
}

/**
 * 右栏段落的锚点放到右侧页边距。
 *
 * 双栏论文里左右两栏的段落常处在同一高度，如果锚点一律放左边，两栏的锚点会重叠，
 * 也不容易看出某条记录属于哪一栏。这里按段落的左边界在不在右半页来判栏位：通栏的
 * 标题、摘要左边界都靠左，会稳定落在左页边距，不会因为右边距差一点点就左右横跳。
 */
const markerOnRight = (block: Block) => block.x0 > 0.5

/** 只有问过问题或写过笔记的段落才留痕。读过的段落不留痕迹，页面才干净。 */
const isFlagged = (block: Block) => block.message_count > 0 || block.has_note > 0

export function PageView({
  pdf,
  index,
  size,
  scale,
  blocks,
  openBlockId,
  selectedIds,
  onActivate,
}: Props) {
  const width = size.width * scale
  const height = size.height * scale
  const holderRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [visible, setVisible] = useState(false)
  const [rendered, setRendered] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 滚动到附近才渲染，几十页的文献也不会一次性占满内存。
  useEffect(() => {
    const holder = holderRef.current
    if (!holder) return
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          // 远离视口后释放高清画布；几十页的文献不会一直把像素堆在内存里。
          setVisible(entry.isIntersecting)
        }
      },
      { rootMargin: '800px 0px' },
    )
    observer.observe(holder)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!visible) {
      if (canvas) {
        canvas.width = 0
        canvas.height = 0
      }
      setRendered(false)
      return
    }
    let cancelled = false
    let task: { cancel: () => void; promise: Promise<unknown> } | null = null
    setError(null)
    // 重画期间先标成未就绪，免得别处（比如气泡里的原图）拿半成品画布去裁图。
    setRendered(false)

    const run = async () => {
      try {
        const page = await pdf.getPage(index + 1)
        if (cancelled) return
        const viewport = page.getViewport({ scale })
        if (!canvas) return

        // 屏幕像素比只有 1 时，PDF 文字会明显比原阅读器糊；至少按 2 倍渲染，
        // 再用 CSS 尺寸压回页面大小，细节就留住了。上限 2.5 控制多页内存。
        const ratio = Math.min(2.5, Math.max(window.devicePixelRatio || 1, 2))
        canvas.width = Math.floor(viewport.width * ratio)
        canvas.height = Math.floor(viewport.height * ratio)
        canvas.style.width = `${viewport.width}px`
        canvas.style.height = `${viewport.height}px`

        const context = canvas.getContext('2d')
        if (!context) return
        task = page.render({
          canvasContext: context,
          viewport,
          transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
        })
        await task.promise
      } catch (reason) {
        // 缩放或翻页时会主动取消上一次渲染，PDF.js 用抛异常表示取消，这不算失败。
        if (cancelled) return
        setError(errorMessage(reason))
        return
      }
      if (!cancelled) setRendered(true)
    }

    void run()
    return () => {
      cancelled = true
      task?.cancel()
    }
  }, [pdf, index, scale, visible])

  return (
    <div className="page" ref={holderRef} data-page={index} style={{ width, height }}>
      <canvas
        ref={canvasRef}
        className="page-canvas"
        data-rendered={rendered ? 'ready' : 'pending'}
      />
      {!rendered && !error && <div className="page-skeleton" aria-hidden />}
      {error && <div className="page-error">这一页渲染失败：{error}</div>}

      {blocks.map((block) => {
        const left = block.x0 * width
        const top = block.y0 * height
        const boxWidth = (block.x1 - block.x0) * width
        const boxHeight = (block.y1 - block.y0) * height
        const onRight = markerOnRight(block)
        const flagged = isFlagged(block)
        const open = openBlockId === block.id
        const selected = selectedIds.has(block.id)
        const questioned = block.message_count > 0

        return (
          <div
            key={block.id}
            className="block"
            style={{ left, top, width: boxWidth, height: boxHeight }}
          >
            <div
              data-block={block.id}
              className={[
                'block-hit',
                open ? 'is-open' : '',
                selected ? 'is-selected' : '',
                questioned ? 'is-questioned' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              onClick={(event) => {
                // 正在拖选文字时不弹窗；Shift 多选不受影响。
                if (!event.shiftKey && window.getSelection()?.toString()) return
                onActivate(block.id, event)
              }}
            />
            <button
              type="button"
              data-marker-block={block.id}
              aria-label={flagged ? '这段有记录，打开气泡' : '打开这段的气泡'}
              className={[
                'marker',
                flagged ? 'is-flagged' : 'is-ghost',
                block.has_note > 0 ? 'has-note' : '',
                block.message_count > 0 ? 'has-question' : '',
                open ? 'is-open' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              // 锚点固定贴在页边距上，所以偏移要减去段落自身的左边距。
              style={
                onRight
                  ? { right: -((1 - block.x1) * width) - 20 }
                  : { left: -left - 20 }
              }
              onClick={(event) => {
                event.stopPropagation()
                onActivate(block.id, event)
              }}
            />
          </div>
        )
      })}
    </div>
  )
}
