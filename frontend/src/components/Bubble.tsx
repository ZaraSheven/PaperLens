import { useEffect, useRef, useState } from 'react'
import type { PDFDocumentProxy } from 'pdfjs-dist'

import { api } from '../api'
import { useQueriedElement, useTrackedRect } from '../hooks/useTrackedRect'
import { drawCrop, previewRenderScale, renderPageSurface } from '../pdfCrop'
import { placeBubble, toBox, type Placement } from '../placement'
import { readAutoNote, writeAutoNote } from '../settings'
import type { AskScope, Block, InlineSegment, Message, PageSize } from '../types'
import { errorMessage } from '../util'
import { MessageBody } from './MessageBody'

type Tab = 'translation' | 'chat' | 'note'

interface Props {
  block: Block
  onClose: () => void
  onUpdate: (block: Block) => void
  onError: (message: string) => void
  /** PDF 原文；气泡里的公式和图都直接从这里重新高清渲染。 */
  pdf: PDFDocumentProxy
  /** 当前页的原始尺寸，用来把归一化坐标还原成显示尺寸。 */
  pageSize: PageSize
  /** 当前阅读缩放。 */
  displayScale: number
}

const KIND_LABEL: Record<Block['kind'], string> = {
  text: '正文',
  formula: '公式',
  figure: '图表',
  table: '表格',
}

/**
 * 把段落所在的那一小块页面截出来。
 *
 * 公式和插图的文字是抽不准的：公式抽出来是一堆错位的符号，插图干脆没有文字。
 * 与其让用户看乱码，不如直接把原页面那一块画出来给他看。
 */
function BlockPreview({
  block,
  pageSize,
  displayScale,
  surface,
}: {
  block: Block
  pageSize: PageSize
  displayScale: number
  surface: HTMLCanvasElement | null
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    if (!surface || !canvasRef.current) return
    drawCrop(canvasRef.current, surface, block, pageSize, displayScale)
  }, [surface, block, pageSize, displayScale])

  return <canvas ref={canvasRef} className="block-preview" />
}

/** 段落里的一个行内公式片段，从高清页面画布裁出来。 */
function InlineFormula({
  segment,
  pageSize,
  displayScale,
  surface,
}: {
  segment: InlineSegment
  pageSize: PageSize
  displayScale: number
  surface: HTMLCanvasElement | null
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    if (!surface || !canvasRef.current) return
    drawCrop(canvasRef.current, surface, segment, pageSize, displayScale, 0.8)
  }, [surface, segment, pageSize, displayScale])

  return (
    <canvas
      ref={canvasRef}
      className="inline-math"
      title={segment.text}
      aria-label={`公式 ${segment.text}`}
      style={{
        width: `${(segment.x1 - segment.x0) * pageSize.width * displayScale}px`,
        height: `${(segment.y1 - segment.y0) * pageSize.height * displayScale}px`,
      }}
    />
  )
}

/** 正文优先按片段渲染；行内公式显示原式，其余文字仍可选中。 */
function BlockSource({
  block,
  pageSize,
  displayScale,
  surface,
}: {
  block: Block
  pageSize: PageSize
  displayScale: number
  surface: HTMLCanvasElement | null
}) {
  if (!block.segments?.length) return <p className="source">{block.text}</p>
  return (
    <p className="source">
      {block.segments.map((segment, index) =>
        segment.kind === 'math' ? (
          <InlineFormula
            key={`${segment.x0}-${segment.y0}-${index}`}
            segment={segment}
            pageSize={pageSize}
            displayScale={displayScale}
            surface={surface}
          />
        ) : (
          <span key={`${segment.x0}-${segment.y0}-${index}`}>{segment.text}</span>
        ),
      )}
    </p>
  )
}

export function Bubble({
  block,
  onClose,
  onUpdate,
  onError,
  pdf,
  pageSize,
  displayScale,
}: Props) {
  const [tab, setTab] = useState<Tab>('translation')
  const [messages, setMessages] = useState<Message[]>([])
  const [scope, setScope] = useState<AskScope>('full')
  const [draft, setDraft] = useState('')
  const [note, setNote] = useState(block.note ?? '')
  const [busy, setBusy] = useState(false)
  const [showPreview, setShowPreview] = useState(block.kind !== 'text')
  const [autoNote, setAutoNote] = useState(readAutoNote)
  /** 笔记已经覆盖到第几条对话。用来判断关窗时要不要重新整理。 */
  const [notedCount, setNotedCount] = useState(0)
  const [placed, setPlaced] = useState<{ x: number; y: number; placement: Placement } | null>(null)
  const [surface, setSurface] = useState<HTMLCanvasElement | null>(null)

  const bubbleRef = useRef<HTMLDivElement>(null)
  // 段落切换后，先前发出去的请求可能才回来。拿它判断结果还该不该往界面上写。
  const currentBlockId = useRef(block.id)
  currentBlockId.current = block.id
  const anchorElement = useQueriedElement(`[data-marker-block="${block.id}"]`)
  const anchorRect = useTrackedRect(anchorElement, displayScale)
  const blockElement = useQueriedElement(`[data-block="${block.id}"]`)
  const blockRect = useTrackedRect(blockElement, displayScale)

  // 当前页只高清渲染一次，段落原图和所有行内公式共用它，避免一页里反复重画。
  useEffect(() => {
    let cancelled = false
    setSurface(null)
    renderPageSurface(pdf, block.page, previewRenderScale(displayScale))
      .then((canvas) => {
        if (!cancelled) setSurface(canvas)
      })
      .catch((reason: unknown) => {
        if (!cancelled) onError(`原文高清渲染失败：${errorMessage(reason)}`)
      })
    return () => {
      cancelled = true
    }
  }, [pdf, block.page, displayScale, onError])

  // 换到另一个段落时重置界面，并把历史对话取回来。
  useEffect(() => {
    let cancelled = false
    setTab('translation')
    setDraft('')
    setMessages([])
    setNote(block.note ?? '')
    setShowPreview(block.kind !== 'text')
    api
      .blockMessages(block.id)
      .then((list) => {
        if (cancelled) return
        setMessages(list)
        // 已经写过笔记就当作它覆盖了现有对话，免得一关窗就重新整理一遍。
        setNotedCount(block.note ? list.length : 0)
      })
      .catch((reason: unknown) => {
        if (!cancelled) onError(errorMessage(reason))
      })
    return () => {
      cancelled = true
    }
  }, [block.id])

  useEffect(() => {
    const element = bubbleRef.current
    // 用段落本身当锚，不用页边那个小圆点。圆点落在页边距里，离正文有一百多像素，
    // 气泡贴着它弹出来会显得离文章很远。
    const anchorBox = blockRect ?? anchorRect
    if (!element || !anchorBox) return
    const measure = () => {
      const box = element.getBoundingClientRect()
      setPlaced(
        placeBubble(
          toBox(anchorBox),
          toBox(anchorBox),
          { w: box.width, h: box.height },
          { w: window.innerWidth, h: window.innerHeight },
        ),
      )
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [anchorRect, blockRect, tab, messages.length, block.note, showPreview])

  // 段落滚出视口后气泡自动收起，不留漂浮窗口。
  useEffect(() => {
    if (!anchorRect) return
    if (anchorRect.bottom < 0 || anchorRect.top > window.innerHeight) onClose()
  }, [anchorRect, onClose])

  const generateNote = async (): Promise<Block> => {
    const next = await api.generateBlockNote(block.id)
    return next
  }

  /** 关闭前按需整理笔记。用户把「自动笔记」关掉时就只是关掉。 */
  const requestClose = async () => {
    const targetId = block.id
    const stale = messages.length > 0 && messages.length > notedCount
    if (!autoNote || !stale) {
      onClose()
      return
    }
    setBusy(true)
    try {
      const next = await generateNote()
      if (currentBlockId.current === targetId) {
        onUpdate(next)
        setNote(next.note ?? '')
        setNotedCount(messages.length)
      }
    } catch (reason) {
      onError(`自动整理笔记失败：${errorMessage(reason)}`)
    } finally {
      setBusy(false)
      onClose()
    }
  }

  // 用 ref 拿最新的关闭逻辑，免得每敲一个字都重新挂一次键盘监听。
  const closeRef = useRef(requestClose)
  closeRef.current = requestClose
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') void closeRef.current()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const guard = async (work: () => Promise<void>) => {
    setBusy(true)
    try {
      await work()
    } catch (reason) {
      onError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  const translate = () => guard(async () => onUpdate(await api.translateBlock(block.id)))

  const send = () =>
    guard(async () => {
      const content = draft.trim()
      if (!content) return
      const targetId = block.id
      setDraft('')
      const result = await api.askBlock(targetId, content, scope)
      const list = await api.blockMessages(targetId)
      if (currentBlockId.current !== targetId) return
      setMessages(list)
      if (result.block) onUpdate(result.block)
    })

  const regenerateNote = () =>
    guard(async () => {
      const targetId = block.id
      const next = await generateNote()
      if (currentBlockId.current !== targetId) return
      onUpdate(next)
      setNote(next.note ?? '')
      setNotedCount(messages.length)
    })

  const saveNote = () => guard(async () => onUpdate(await api.patchBlock(block.id, { note })))

  return (
    <div
      ref={bubbleRef}
      className={[
        'bubble',
        `placement-${placed?.placement ?? 'right'}`,
        block.kind === 'text' ? '' : 'is-wide',
      ]
        .filter(Boolean)
        .join(' ')}
      style={{
        left: placed?.x ?? 0,
        top: placed?.y ?? 0,
        visibility: placed ? 'visible' : 'hidden',
      }}
      role="dialog"
      aria-label="段落气泡"
    >
      <header className="bubble-head">
        <span className="bubble-page">第 {block.page + 1} 页</span>
        <span className="kind-chip">{KIND_LABEL[block.kind]}</span>
        {block.message_count > 0 && <span className="flag-chip">有疑问</span>}
        <label className="toggle" title="关掉气泡时自动把这段的问答整理成笔记">
          <input
            type="checkbox"
            checked={autoNote}
            onChange={(event) => {
              setAutoNote(event.target.checked)
              writeAutoNote(event.target.checked)
            }}
          />
          自动笔记
        </label>
        <button type="button" className="icon" onClick={() => void requestClose()} aria-label="关闭">
          ✕
        </button>
      </header>

      <nav className="bubble-tabs">
        {(
          [
            ['translation', '翻译'],
            ['chat', '对话'],
            ['note', '笔记'],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={tab === key ? 'tab active' : 'tab'}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
        {block.kind === 'text' && (
          <button
            type="button"
            className="tab"
            onClick={() => setShowPreview((value) => !value)}
          >
            {showPreview ? '收起原文' : '看原文'}
          </button>
        )}
      </nav>

      <div className="bubble-body">
        {showPreview && (
          <div className="preview">
            <BlockPreview
              block={block}
              pageSize={pageSize}
              displayScale={displayScale}
              surface={surface}
            />
          </div>
        )}

        {tab === 'translation' && (
          <section className="pane">
            {block.kind === 'figure' ? (
              <p className="empty">图表按原图显示。可以直接在对话里问它相关的问题。</p>
            ) : block.kind === 'table' ? (
              <p className="empty">表格按原图显示，避免单元格被拆散后翻译错位。</p>
            ) : block.kind === 'formula' ? (
              <p className="empty">公式按原图显示，避免抽取后的符号顺序错乱。</p>
            ) : (
              <>
                <BlockSource
                  block={block}
                  pageSize={pageSize}
                  displayScale={displayScale}
                  surface={surface}
                />
                {block.translation ? (
                  <>
                    <p className="translated">{block.translation}</p>
                    <button type="button" className="ghost" onClick={translate} disabled={busy}>
                      重新翻译
                    </button>
                  </>
                ) : (
                  <button type="button" className="primary" onClick={translate} disabled={busy}>
                    {busy ? '翻译中…' : '翻译这段'}
                  </button>
                )}
              </>
            )}
          </section>
        )}

        {tab === 'chat' && (
          <section className="pane chat">
            <div className="messages">
              {messages.length === 0 && <p className="empty">还没有提问</p>}
              {messages.map((message) => (
                <div key={message.id} className={`message role-${message.role}`}>
                  <MessageBody content={message.content} />
                </div>
              ))}
              {busy && <p className="empty">正在回答…</p>}
            </div>
            <div className="composer">
              <div className="scope">
                <button
                  type="button"
                  className={scope === 'full' ? 'chip active' : 'chip'}
                  onClick={() => setScope('full')}
                >
                  全文
                </button>
                <button
                  type="button"
                  className={scope === 'block' ? 'chip active' : 'chip'}
                  onClick={() => setScope('block')}
                >
                  本段
                </button>
              </div>
              <textarea
                value={draft}
                placeholder="这段没看懂什么？"
                rows={2}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    void send()
                  }
                }}
              />
              <button
                type="button"
                className="primary"
                onClick={send}
                disabled={busy || !draft.trim()}
              >
                提问
              </button>
            </div>
          </section>
        )}

        {tab === 'note' && (
          <section className="pane">
            <div className="note-actions">
              <button type="button" className="primary" onClick={regenerateNote} disabled={busy}>
                {busy ? '整理中…' : '按问答生成笔记'}
              </button>
              <button type="button" className="ghost" onClick={saveNote} disabled={busy}>
                保存
              </button>
            </div>
            <textarea
              className="note-editor"
              value={note}
              rows={10}
              placeholder="这段的笔记"
              onChange={(event) => setNote(event.target.value)}
            />
          </section>
        )}
      </div>
    </div>
  )
}
