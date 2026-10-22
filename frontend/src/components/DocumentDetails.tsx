import { useEffect, useState } from 'react'

import { api } from '../api'
import type { DocumentDetails as Details } from '../types'
import { errorMessage } from '../util'
import { MessageBody } from './MessageBody'

interface Props {
  docId: string | null
  onClose: () => void
  onOpen: (docId: string) => void
}

export function DocumentDetails({ docId, onClose, onOpen }: Props) {
  const [details, setDetails] = useState<Details | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!docId) {
      setDetails(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .documentDetails(docId)
      .then((result) => {
        if (!cancelled) setDetails(result)
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(errorMessage(reason))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [docId])

  if (!docId) return null

  return (
    <div className="details-overlay" onClick={onClose}>
      <article className="details-modal" onClick={(event) => event.stopPropagation()}>
        <header className="details-head">
          <div>
            <span className="setup-kicker">论文详情</span>
            <h2>{details?.document.title || details?.document.filename || '正在读取…'}</h2>
            {details && (
              <p>
                {details.document.read_status === 'read' ? '已读' : '待读'} ·{' '}
                {details.document.category || '未分类'} · {details.document.page_count} 页 ·{' '}
                {details.document.block_count} 块
              </p>
            )}
          </div>
          <div className="details-head-actions">
            <button type="button" className="primary" onClick={() => onOpen(docId)}>
              进入阅读
            </button>
            <button type="button" className="icon" onClick={onClose} aria-label="关闭">
              ✕
            </button>
          </div>
        </header>

        {loading && <p className="empty">正在生成论文梗概…</p>}
        {error && <div className="banner error">{error}</div>}

        {details && (
          <div className="details-body">
            <section>
              <h3>论文梗概</h3>
              <p>{details.overview.summary || '暂无'}</p>
            </section>
            <section>
              <h3>使用的方法</h3>
              {details.overview.methods.length ? (
                <ul>
                  {details.overview.methods.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className="empty">暂无</p>
              )}
            </section>
            <section>
              <h3>解决的问题</h3>
              {details.overview.problems.length ? (
                <ul>
                  {details.overview.problems.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className="empty">暂无</p>
              )}
            </section>
            <section>
              <h3>结论</h3>
              <p>{details.overview.conclusion || '暂无'}</p>
            </section>
            <section>
              <h3>我的疑问和解答</h3>
              {details.questions.length ? (
                <div className="details-questions">
                  {details.questions.map((entry) => (
                    <div key={entry.block.id} className="details-question">
                      <p className="details-question-text">
                        第 {entry.block.page + 1} 页：{entry.block.first_question || '只写了笔记'}
                      </p>
                      {entry.messages
                        .filter((message) => message.role === 'assistant')
                        .slice(-1)
                        .map((message) => (
                          <div key={message.id} className="details-answer">
                            <MessageBody content={message.content} />
                          </div>
                        ))}
                      {entry.block.note && <p className="details-note">{entry.block.note}</p>}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="empty">还没有留下疑问</p>
              )}
            </section>
          </div>
        )}
      </article>
    </div>
  )
}
