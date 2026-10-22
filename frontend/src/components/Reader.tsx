import { useCallback, useEffect, useMemo, useState, type MouseEvent } from 'react'
import { createPortal } from 'react-dom'

import { api } from '../api'
import { usePdf } from '../hooks/usePdf'
import type { Block, DocumentRecord } from '../types'
import { errorMessage } from '../util'
import { Bubble } from './Bubble'
import { DocPanel, type PanelTab } from './DocPanel'
import { PageView } from './PageView'

const MIN_SCALE = 0.6
const MAX_SCALE = 3
const SCALE_STEP = 0.15

export function Reader({ docId, onBack }: { docId: string; onBack: () => void }) {
  const { doc, sizes, error: pdfError } = usePdf(`/api/documents/${docId}/file`)
  const [record, setRecord] = useState<DocumentRecord | null>(null)
  const [blocks, setBlocks] = useState<Block[]>([])
  const [scale, setScale] = useState(1.2)
  const [openBlockId, setOpenBlockId] = useState<string | null>(null)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectionAnchor, setSelectionAnchor] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [selectionBusy, setSelectionBusy] = useState(false)
  const [panel, setPanel] = useState<'none' | PanelTab>('none')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setOpenBlockId(null)
    setSelectionMode(false)
    setSelectionAnchor(null)
    setSelectedIds([])
    setPanel('none')
    setBlocks([])
    api
      .blocks(docId)
      .then((list) => {
        if (!cancelled) setBlocks(list)
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(errorMessage(reason))
      })
    api
      .documentNote(docId)
      .then((result) => {
        if (!cancelled) setRecord(result.document)
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(errorMessage(reason))
      })
    return () => {
      cancelled = true
    }
  }, [docId])

  const byPage = useMemo(() => {
    const grouped = new Map<number, Block[]>()
    for (const block of blocks) {
      const list = grouped.get(block.page)
      if (list) list.push(block)
      else grouped.set(block.page, [block])
    }
    return grouped
  }, [blocks])

  const byId = useMemo(() => new Map(blocks.map((block) => [block.id, block])), [blocks])
  const openBlock = openBlockId ? byId.get(openBlockId) ?? null : null
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds])
  const selectedBlocks = useMemo(
    () =>
      selectedIds
        .map((blockId) => byId.get(blockId))
        .filter((block): block is Block => Boolean(block)),
    [byId, selectedIds],
  )
  const questionCount = blocks.filter((block) => block.message_count > 0).length
  const noteCount = blocks.filter((block) => block.has_note > 0).length

  const replaceBlock = useCallback((next: Block) => {
    setBlocks((previous) => previous.map((block) => (block.id === next.id ? next : block)))
  }, [])
  const showError = useCallback((message: string) => setError(message), [])

  const clearSelection = useCallback(() => {
    setSelectedIds([])
    setSelectionAnchor(null)
  }, [])

  const toggleSelectionMode = useCallback(() => {
    if (selectionMode) {
      setSelectionMode(false)
      clearSelection()
    } else {
      setSelectionMode(true)
      setOpenBlockId(null)
    }
  }, [clearSelection, selectionMode])

  const activateBlock = useCallback(
    (blockId: string, event: MouseEvent<HTMLElement>) => {
      const extend = event.shiftKey
      if (selectionMode || extend) {
        event.preventDefault()
        const anchorId = extend ? selectionAnchor ?? blockId : blockId
        const ids = blocks.map((block) => block.id)
        const anchorIndex = ids.indexOf(anchorId)
        const targetIndex = ids.indexOf(blockId)
        if (!extend || anchorIndex < 0 || targetIndex < 0) {
          setSelectedIds([blockId])
          setSelectionAnchor(blockId)
        } else {
          const start = Math.min(anchorIndex, targetIndex)
          const end = Math.max(anchorIndex, targetIndex)
          setSelectedIds(ids.slice(start, end + 1))
          setSelectionAnchor(anchorId)
        }
        setOpenBlockId(null)
        return
      }
      clearSelection()
      setSelectionAnchor(blockId)
      setOpenBlockId(blockId)
    },
    [blocks, clearSelection, selectionAnchor, selectionMode],
  )

  const copySelected = useCallback(async () => {
    const text = selectedBlocks.map((block) => block.text).join('\n\n').trim()
    if (!text) {
      showError('选中的块没有可复制文字')
      return
    }
    try {
      await navigator.clipboard.writeText(text)
    } catch (reason) {
      showError(`复制失败：${errorMessage(reason)}`)
    }
  }, [selectedBlocks, showError])

  const translateSelected = useCallback(async () => {
    const targets = selectedBlocks.filter((block) => block.kind === 'text')
    if (!targets.length) {
      showError('选中的内容没有可翻译的正文')
      return
    }
    setSelectionBusy(true)
    try {
      for (const block of targets) {
        replaceBlock(await api.translateBlock(block.id))
      }
    } catch (reason) {
      showError(`翻译选中段落失败：${errorMessage(reason)}`)
    } finally {
      setSelectionBusy(false)
    }
  }, [replaceBlock, selectedBlocks, showError])

  const jumpTo = useCallback((blockId: string) => {
    document.querySelector(`[data-block="${blockId}"]`)?.scrollIntoView({ block: 'center' })
    // 等浏览器把这帧的滚动做完再开气泡；否则锚点还在视口外，气泡会被立刻收起。
    requestAnimationFrame(() => setOpenBlockId(blockId))
  }, [])

  const zoom = (delta: number) =>
    setScale((current) =>
      Math.min(MAX_SCALE, Math.max(MIN_SCALE, Number((current + delta).toFixed(2)))),
    )

  return (
    <div className="reader">
      <header className="toolbar">
        <button type="button" className="ghost" onClick={onBack}>
          返回
        </button>
        <span className="toolbar-title">{record?.title || record?.filename || '加载中…'}</span>
        <span className="toolbar-progress">
          疑问 {questionCount} · 笔记 {noteCount}
        </span>
        <a
          className="tab"
          href={`/api/documents/${docId}/file`}
          target="_blank"
          rel="noreferrer"
          title="用浏览器原生 PDF 查看器打开原文件"
        >
          原文件
        </a>
        <button
          type="button"
          className={selectionMode ? 'tab active' : 'tab'}
          onClick={toggleSelectionMode}
          title="按住 Shift 点段落，可以连续选择多段"
        >
          多选{selectedIds.length ? ` ${selectedIds.length}` : ''}
        </button>
        <div className="zoom">
          <button type="button" className="ghost" onClick={() => zoom(-SCALE_STEP)} aria-label="缩小">
            −
          </button>
          <span className="zoom-value">{Math.round(scale * 100)}%</span>
          <button type="button" className="ghost" onClick={() => zoom(SCALE_STEP)} aria-label="放大">
            +
          </button>
        </div>
        <button
          type="button"
          className={panel === 'issues' ? 'tab active' : 'tab'}
          onClick={() => setPanel(panel === 'issues' ? 'none' : 'issues')}
        >
          疑问清单
        </button>
        <button
          type="button"
          className={panel === 'chat' ? 'tab active' : 'tab'}
          onClick={() => setPanel(panel === 'chat' ? 'none' : 'chat')}
        >
          全文对话
        </button>
        <button
          type="button"
          className={panel === 'note' ? 'tab active' : 'tab'}
          onClick={() => setPanel(panel === 'note' ? 'none' : 'note')}
        >
          文献笔记
        </button>
      </header>

      {error && (
        <div className="banner error">
          {error}
          <button type="button" className="ghost" onClick={() => setError(null)}>
            知道了
          </button>
        </div>
      )}
      {pdfError && <div className="banner error">PDF 打不开：{pdfError}</div>}

      <div className="viewer">
        {doc && (
          <div className="pages">
            {sizes.map((size, index) => (
              <PageView
                key={index}
                pdf={doc}
                index={index}
                size={size}
                scale={scale}
                blocks={byPage.get(index) ?? []}
                openBlockId={openBlockId}
                selectedIds={selectedSet}
                onActivate={activateBlock}
              />
            ))}
          </div>
        )}
      </div>

      {panel !== 'none' && (
        <DocPanel
          key={panel}
          docId={docId}
          initialTab={panel}
          onJump={jumpTo}
          onClose={() => setPanel('none')}
          onError={showError}
        />
      )}

      {selectedIds.length > 0 && (
        <div className="selection-bar">
          <span className="selection-count">已选 {selectedIds.length} 段</span>
          <button type="button" className="ghost" onClick={() => void copySelected()}>
            复制原文
          </button>
          <button
            type="button"
            className="primary"
            disabled={selectionBusy}
            onClick={() => void translateSelected()}
          >
            {selectionBusy ? '翻译中…' : '翻译选中'}
          </button>
          <button type="button" className="ghost" onClick={clearSelection}>
            清除
          </button>
        </div>
      )}

      {doc &&
        openBlock &&
        sizes[openBlock.page] &&
        createPortal(
          <Bubble
            block={openBlock}
            onClose={() => setOpenBlockId(null)}
            onUpdate={replaceBlock}
            onError={showError}
            pdf={doc}
            pageSize={sizes[openBlock.page]}
            displayScale={scale}
          />,
          document.body,
        )}
    </div>
  )
}
