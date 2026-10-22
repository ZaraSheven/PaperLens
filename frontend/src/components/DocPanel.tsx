import { useEffect, useState } from 'react'

import { api } from '../api'
import type { Message, Question } from '../types'
import { errorMessage } from '../util'
import { MessageBody } from './MessageBody'

export type PanelTab = 'chat' | 'issues' | 'note'

interface Props {
  docId: string
  initialTab: PanelTab
  onJump: (blockId: string) => void
  onClose: () => void
  onError: (message: string) => void
}

export function DocPanel({ docId, initialTab, onJump, onClose, onError }: Props) {
  const [tab, setTab] = useState<PanelTab>(initialTab)
  const [messages, setMessages] = useState<Message[]>([])
  const [questions, setQuestions] = useState<Question[]>([])
  const [draft, setDraft] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .documentMessages(docId)
      .then((list) => {
        if (!cancelled) setMessages(list)
      })
      .catch((reason: unknown) => {
        if (!cancelled) onError(errorMessage(reason))
      })
    api
      .questions(docId)
      .then((list) => {
        if (!cancelled) setQuestions(list)
      })
      .catch((reason: unknown) => {
        if (!cancelled) onError(errorMessage(reason))
      })
    api
      .documentNote(docId)
      .then((result) => {
        if (!cancelled) setNote(result.note)
      })
      .catch((reason: unknown) => {
        if (!cancelled) onError(errorMessage(reason))
      })
    return () => {
      cancelled = true
    }
  }, [docId])

  const ask = async () => {
    const content = draft.trim()
    if (!content || busy) return
    setBusy(true)
    try {
      // 全文面板没有段落锚点，检索范围固定是整篇。
      await api.askDocument(docId, content, 'full')
      setDraft('')
      setMessages(await api.documentMessages(docId))
    } catch (reason) {
      onError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  const save = async () => {
    try {
      await api.saveDocumentNote(docId, note)
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    } catch (reason) {
      onError(errorMessage(reason))
    }
  }

  return (
    <aside className="doc-panel">
      <header className="panel-head">
        {(
          [
            ['issues', '疑问清单'],
            ['chat', '全文对话'],
            ['note', '文献笔记'],
          ] as [PanelTab, string][]
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
        <button type="button" className="icon" onClick={onClose} aria-label="关闭">
          ✕
        </button>
      </header>

      {tab === 'issues' && (
        <div className="issue-list">
          {questions.length === 0 && (
            <p className="empty">还没有标记。问过问题的段落会自动出现在这里。</p>
          )}
          {questions.map((item) => (
            <button
              key={item.id}
              type="button"
              className="issue"
              onClick={() => onJump(item.id)}
            >
              <span className="issue-head">
                <span className="issue-page">第 {item.page + 1} 页</span>
                {item.message_count > 0 && <span className="flag-chip">问过 {item.message_count} 次</span>}
                {item.note && <span className="kind-chip">有笔记</span>}
              </span>
              <span className="issue-question">{item.first_question || '（只写了笔记）'}</span>
              <span className="issue-source">{item.text.slice(0, 90)}</span>
            </button>
          ))}
        </div>
      )}

      {tab === 'chat' && (
        <>
          <div className="messages">
            {messages.length === 0 && <p className="empty">针对整篇文献提问</p>}
            {messages.map((message) => (
              <div key={message.id} className={`message role-${message.role}`}>
                <MessageBody content={message.content} />
              </div>
            ))}
            {busy && <p className="empty">正在回答…</p>}
          </div>
          <div className="composer">
            <textarea
              value={draft}
              rows={2}
              placeholder="这篇文献的问题"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  void ask()
                }
              }}
            />
            <button type="button" className="primary" onClick={ask} disabled={busy || !draft.trim()}>
              提问
            </button>
          </div>
        </>
      )}

      {tab === 'note' && (
        <div className="note-pane">
          <div className="note-actions">
            <button type="button" className="primary" onClick={save}>
              {saved ? '已保存' : '保存笔记'}
            </button>
            <a className="link-button" href={`/api/documents/${docId}/markdown`} download>
              导出全部记录
            </a>
          </div>
          <textarea
            className="note-editor"
            rows={18}
            value={note}
            placeholder="整篇文献的笔记、综述素材、待查问题"
            onChange={(event) => setNote(event.target.value)}
          />
        </div>
      )}
    </aside>
  )
}
