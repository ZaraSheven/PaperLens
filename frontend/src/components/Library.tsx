import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'

import { api } from '../api'
import { readCollapsedFolders, writeCollapsedFolders } from '../settings'
import type { Appearance, Skin } from '../skins'
import type { DocumentRecord } from '../types'
import { errorMessage } from '../util'
import { DocumentDetails } from './DocumentDetails'
import { SkinPicker } from './SkinPicker'

/** 未分类固定用这个 key，避免和用户自建的同名分类撞在一起。 */
const UNCATEGORIZED = '__uncategorized__'

interface Folder {
  key: string
  label: string
  documents: DocumentRecord[]
}

/**
 * 栏目里的文件夹：先用户自建的分类，最后是未分类。
 * 有文献的排在前面，空的沉到后面，免得空文件夹把正文挤下去。
 */
function buildFolders(documents: DocumentRecord[], categories: string[]): Folder[] {
  const folders: Folder[] = categories.map((name) => ({
    key: name,
    label: name,
    documents: documents.filter((item) => item.category === name),
  }))
  folders.push({
    key: UNCATEGORIZED,
    label: '未分类',
    documents: documents.filter((item) => !item.category),
  })
  return folders.sort(
    (left, right) => Number(right.documents.length > 0) - Number(left.documents.length > 0),
  )
}

function DocumentColumn({
  columnKey,
  title,
  documents,
  categories,
  emptyText,
  collapsed,
  onToggleFolder,
  onActivate,
  onOpenReader,
  onDelete,
  onCategory,
  onToggleStatus,
}: {
  columnKey: 'unread' | 'read'
  title: string
  documents: DocumentRecord[]
  categories: string[]
  emptyText: string
  collapsed: Set<string>
  onToggleFolder: (key: string) => void
  onActivate: (item: DocumentRecord, event: MouseEvent<HTMLButtonElement>) => void
  onOpenReader: (docId: string) => void
  onDelete: (docId: string) => void
  onCategory: (docId: string, category: string) => void
  onToggleStatus: (item: DocumentRecord) => void
}) {
  const folders = buildFolders(documents, categories)

  return (
    <section className="doc-column">
      <header className="doc-column-head">
        <h2>{title}</h2>
        <span>{documents.length}</span>
      </header>
      {documents.length === 0 && <p className="empty doc-column-empty">{emptyText}</p>}
      {documents.length > 0 && (
        <div className="folder-list">
          {folders.map((folder) => {
            const folderKey = `${columnKey}:${folder.key}`
            const isCollapsed = collapsed.has(folderKey)
            const isEmpty = folder.documents.length === 0
            return (
              <section
                key={folder.key}
                data-folder={folderKey}
                className={isEmpty ? 'folder is-empty' : 'folder'}
              >
                <button
                  type="button"
                  className="folder-head"
                  disabled={isEmpty}
                  aria-expanded={isEmpty ? undefined : !isCollapsed}
                  onClick={() => onToggleFolder(folderKey)}
                >
                  {!isEmpty && (
                    <span className="folder-caret" aria-hidden="true">
                      {isCollapsed ? '▸' : '▾'}
                    </span>
                  )}
                  <span className="folder-name">{folder.label}</span>
                  <span className="folder-count">{folder.documents.length}</span>
                </button>
                {!isEmpty && !isCollapsed && (
                  <ul className="doc-list">
                    {folder.documents.map((item) => (
                      <li key={item.id} data-doc-id={item.id}>
                        <button
                          type="button"
                          className="doc-open"
                          onClick={(event) => onActivate(item, event)}
                          onDoubleClick={() => {
                            if (item.read_status === 'read') onOpenReader(item.id)
                          }}
                        >
                          <span className="doc-title">{item.title || item.filename}</span>
                          <span className="doc-meta">
                            {item.page_count} 页 · {item.block_count} 段 ·{' '}
                            {item.category || '未分类'}
                          </span>
                        </button>
                        <select
                          className="doc-category"
                          value={item.category}
                          aria-label="文献分类"
                          onClick={(event) => event.stopPropagation()}
                          onChange={(event) => onCategory(item.id, event.target.value)}
                        >
                          <option value="">未分类</option>
                          {categories.map((category) => (
                            <option key={category} value={category}>
                              {category}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          className="ghost doc-action"
                          onClick={(event) => {
                            event.stopPropagation()
                            onToggleStatus(item)
                          }}
                        >
                          {item.read_status === 'read' ? '移回待读' : '标记已读'}
                        </button>
                        <button
                          type="button"
                          className="ghost doc-action"
                          onClick={(event) => {
                            event.stopPropagation()
                            onDelete(item.id)
                          }}
                        >
                          删除
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )
          })}
        </div>
      )}
    </section>
  )
}

export function Library({
  onOpen,
  onConfigure,
  skins,
  appearance,
  onSkins,
  onAppearance,
}: {
  onOpen: (docId: string) => void
  onConfigure: () => void
  skins: Skin[]
  appearance: Appearance
  onSkins: (list: Skin[]) => void
  onAppearance: (appearance: Appearance) => void
}) {
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(readCollapsedFolders)
  const [newCategory, setNewCategory] = useState('')
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [skinOpen, setSkinOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const clickTimer = useRef<number | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [list, categoryResult] = await Promise.all([api.listDocuments(), api.categories()])
      setDocuments(list)
      setCategories(categoryResult.categories)
    } catch (reason) {
      setError(errorMessage(reason))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(
    () => () => {
      if (clickTimer.current !== null) window.clearTimeout(clickTimer.current)
    },
    [],
  )

  const unreadDocuments = useMemo(
    () => documents.filter((item) => item.read_status !== 'read'),
    [documents],
  )
  const readDocuments = useMemo(
    () => documents.filter((item) => item.read_status === 'read'),
    [documents],
  )

  /** 折叠状态按「栏目 + 分类」记在本地，下次打开还是自己收好的样子。 */
  const toggleFolder = (key: string) => {
    setCollapsedFolders((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      writeCollapsedFolders(next)
      return next
    })
  }

  const upload = async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      await api.upload(file)
      await refresh()
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (docId: string) => {
    if (!window.confirm('删除这篇文献以及它的翻译、问答和笔记？')) return
    try {
      await api.deleteDocument(docId)
      await refresh()
    } catch (reason) {
      setError(errorMessage(reason))
    }
  }

  const updateDocument = async (
    docId: string,
    patch: { read_status?: 'unread' | 'read'; category?: string },
  ) => {
    try {
      const updated = await api.updateDocument(docId, patch)
      setDocuments((current) => current.map((item) => (item.id === docId ? updated : item)))
      if (updated.category) setCategories((current) => Array.from(new Set([...current, updated.category])).sort())
    } catch (reason) {
      setError(errorMessage(reason))
    }
  }

  const addCategory = async () => {
    const name = newCategory.trim()
    if (!name) return
    try {
      const result = await api.addCategory(name)
      setCategories(result.categories)
      // 新分类立刻出现在两栏的文件夹列表里（还没有文献，所以排在后面），
      // 用每行的下拉把文献放进去就行。
      setNewCategory('')
    } catch (reason) {
      setError(errorMessage(reason))
    }
  }

  const scheduleDetails = (docId: string) => {
    if (clickTimer.current !== null) window.clearTimeout(clickTimer.current)
    clickTimer.current = window.setTimeout(() => {
      setDetailId(docId)
      clickTimer.current = null
    }, 220)
  }

  const openReader = (docId: string, markRead = true) => {
    if (clickTimer.current !== null) window.clearTimeout(clickTimer.current)
    clickTimer.current = null
    if (markRead) void updateDocument(docId, { read_status: 'read' })
    onOpen(docId)
  }

  const activateDocument = (item: DocumentRecord, event: MouseEvent<HTMLButtonElement>) => {
    if (item.read_status === 'unread') {
      if (event.detail > 1) return
      openReader(item.id)
      return
    }
    if (event.detail > 1) return
    if (event.detail === 0) {
      setDetailId(item.id)
      return
    }
    scheduleDetails(item.id)
  }

  return (
    <div className="library">
      <header className="library-head">
        <div className="library-title">
          <h1>PaperLens</h1>
          <p>待读单击直接进入；已读单击看详情，双击继续阅读。</p>
        </div>
        <button type="button" className="ghost" onClick={() => setSkinOpen(true)}>
          皮肤
        </button>
        <button type="button" className="ghost" onClick={onConfigure}>
          模型设置
        </button>
      </header>

      <div className="library-tools">
        <div className="category-add">
          <input
            value={newCategory}
            placeholder="新建分类（文件夹）"
            maxLength={40}
            onChange={(event) => setNewCategory(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void addCategory()
            }}
          />
          <button type="button" className="ghost" onClick={() => void addCategory()}>
            添加
          </button>
        </div>
      </div>

      <div
        className={`dropzone ${dragging ? 'is-dragging' : ''}`}
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          const file = event.dataTransfer.files[0]
          if (file) void upload(file)
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void upload(file)
            event.target.value = ''
          }}
        />
        <button type="button" className="primary" disabled={busy} onClick={() => inputRef.current?.click()}>
          {busy ? '正在解析…' : '选择 PDF 文件'}
        </button>
        <span className="hint">上传后先进入待读，也可以直接把文件拖进来</span>
      </div>

      {error && <div className="banner error">{error}</div>}

      <div className="library-columns">
        <DocumentColumn
          columnKey="unread"
          title="待读"
          documents={unreadDocuments}
          categories={categories}
          emptyText="没有待读文献"
          collapsed={collapsedFolders}
          onToggleFolder={toggleFolder}
          onActivate={activateDocument}
          onOpenReader={(docId) => openReader(docId, false)}
          onDelete={(docId) => void remove(docId)}
          onCategory={(docId, category) => void updateDocument(docId, { category })}
          onToggleStatus={(item) =>
            void updateDocument(item.id, {
              read_status: item.read_status === 'read' ? 'unread' : 'read',
            })
          }
        />
        <DocumentColumn
          columnKey="read"
          title="已读"
          documents={readDocuments}
          categories={categories}
          emptyText="没有已读文献"
          collapsed={collapsedFolders}
          onToggleFolder={toggleFolder}
          onActivate={activateDocument}
          onOpenReader={(docId) => openReader(docId, false)}
          onDelete={(docId) => void remove(docId)}
          onCategory={(docId, category) => void updateDocument(docId, { category })}
          onToggleStatus={(item) =>
            void updateDocument(item.id, {
              read_status: item.read_status === 'read' ? 'unread' : 'read',
            })
          }
        />
      </div>

      <DocumentDetails
        docId={detailId}
        onClose={() => setDetailId(null)}
        onOpen={(docId) => openReader(docId, false)}
      />

      {skinOpen && (
        <SkinPicker
          skins={skins}
          appearance={appearance}
          onSkins={onSkins}
          onChange={onAppearance}
          onClose={() => setSkinOpen(false)}
          onError={setError}
        />
      )}
    </div>
  )
}
