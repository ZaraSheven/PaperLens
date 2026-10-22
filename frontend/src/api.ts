import type {
  Block,
  DocumentRecord,
  DocumentDetails,
  ConfigInput,
  ConfigResponse,
  HealthStatus,
  Message,
  ModelListInput,
  PageSize,
  Question,
} from './types'
import type { Appearance, Skin } from './skins'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail) detail = JSON.stringify(body.detail)
    } catch {
      // 响应不是 JSON，保留状态码说明。
    }
    throw new Error(detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export interface StreamHandlers {
  /** 每收到一段就交给界面显示，不用等整段生成完 */
  onDelta: (text: string) => void
  onError: (message: string) => void
  onDone?: (messageId: number) => void
}

/** 读一个 SSE 流：问题已经落库，回答一段段推过来。 */
async function streamRequest(
  url: string,
  body: unknown,
  handlers: StreamHandlers,
): Promise<void> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok || !response.body) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const parsed = (await response.json()) as { detail?: unknown }
      if (typeof parsed.detail === 'string') detail = parsed.detail
    } catch {
      // 响应不是 JSON，保留状态码说明。
    }
    handlers.onError(detail)
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // 事件之间用空行分隔，最后一段可能还没收全，留在缓冲里等下一轮。
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const part of parts) {
      const line = part.trim()
      if (!line.startsWith('data:')) continue
      const payload = JSON.parse(line.slice(5).trim()) as {
        type: string
        text?: string
        message?: string
        id?: number
      }
      if (payload.type === 'delta' && payload.text) handlers.onDelta(payload.text)
      else if (payload.type === 'error') handlers.onError(payload.message ?? '模型没答上来')
      else if (payload.type === 'done' && payload.id !== undefined) handlers.onDone?.(payload.id)
    }
  }
}

export const api = {
  health: () => request<HealthStatus>('/api/health'),

  config: () => request<ConfigResponse>('/api/config'),

  saveConfig: (payload: ConfigInput) =>
    request<ConfigResponse>('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  listModels: (payload: ModelListInput) =>
    request<{ models: string[] }>('/api/config/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  skins: () => request<{ skins: Skin[] }>('/api/skins'),

  appearance: () => request<{ appearance: Appearance }>('/api/appearance'),

  saveAppearance: (appearance: Appearance) =>
    request<{ appearance: Appearance }>('/api/appearance', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(appearance),
    }),

  async uploadSkin(name: string, file: File) {
    const form = new FormData()
    form.append('file', file)
    form.append('name', name)
    return request<{ skin: Skin }>('/api/skins', { method: 'POST', body: form })
  },

  deleteSkin: (skinId: string) => request<void>(`/api/skins/${skinId}`, { method: 'DELETE' }),

  listDocuments: () => request<DocumentRecord[]>('/api/documents'),

  updateDocument: (
    docId: string,
    patch: { read_status?: 'unread' | 'read'; category?: string },
  ) =>
    request<DocumentRecord>(`/api/documents/${docId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),

  categories: () => request<{ categories: string[] }>('/api/categories'),

  addCategory: (name: string) =>
    request<{ categories: string[] }>('/api/categories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),

  async upload(file: File) {
    const form = new FormData()
    form.append('file', file)
    return request<{ document: DocumentRecord; blocks: Block[]; pages: PageSize[] }>(
      '/api/documents',
      { method: 'POST', body: form },
    )
  },

  deleteDocument: (docId: string) =>
    request<void>(`/api/documents/${docId}`, { method: 'DELETE' }),

  blocks: (docId: string) => request<Block[]>(`/api/documents/${docId}/blocks`),

  block: (blockId: string) => request<Block>(`/api/blocks/${blockId}`),

  questions: (docId: string) => request<Question[]>(`/api/documents/${docId}/questions`),

  documentDetails: (docId: string, refresh = false) =>
    request<DocumentDetails>(
      `/api/documents/${docId}/overview${refresh ? '?refresh=true' : ''}`,
    ),

  patchBlock: (blockId: string, patch: { translation?: string; note?: string }) =>
    request<Block>(`/api/blocks/${blockId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),

  translateBlock: (blockId: string) =>
    request<Block>(`/api/blocks/${blockId}/translate`, { method: 'POST' }),

  blockMessages: (blockId: string) => request<Message[]>(`/api/blocks/${blockId}/messages`),

  askBlockStream: (blockId: string, content: string, handlers: StreamHandlers) =>
    streamRequest(`/api/blocks/${blockId}/messages/stream`, { content }, handlers),

  clearBlockMessages: (blockId: string) =>
    request<void>(`/api/blocks/${blockId}/messages`, { method: 'DELETE' }),

  generateBlockNote: (blockId: string) =>
    request<Block>(`/api/blocks/${blockId}/note`, { method: 'POST' }),

  documentMessages: (docId: string) => request<Message[]>(`/api/documents/${docId}/messages`),

  askDocumentStream: (docId: string, content: string, handlers: StreamHandlers) =>
    streamRequest(`/api/documents/${docId}/messages/stream`, { content }, handlers),

  documentNote: (docId: string) =>
    request<{ document: DocumentRecord; note: string }>(`/api/documents/${docId}`),

  saveDocumentNote: (docId: string, content: string) =>
    request<{ content: string }>(`/api/documents/${docId}/note`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }),
}

