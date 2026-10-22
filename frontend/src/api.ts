import type {
  AskScope,
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

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

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

  askBlock: (blockId: string, content: string, scope: AskScope) =>
    request<{ message: Message; citations: unknown[]; block: Block }>(
      `/api/blocks/${blockId}/messages`,
      json({ content, scope }),
    ),

  clearBlockMessages: (blockId: string) =>
    request<void>(`/api/blocks/${blockId}/messages`, { method: 'DELETE' }),

  generateBlockNote: (blockId: string) =>
    request<Block>(`/api/blocks/${blockId}/note`, { method: 'POST' }),

  documentMessages: (docId: string) => request<Message[]>(`/api/documents/${docId}/messages`),

  askDocument: (docId: string, content: string, scope: AskScope) =>
    request<{ message: Message; citations: unknown[] }>(
      `/api/documents/${docId}/messages`,
      json({ content, scope }),
    ),

  documentNote: (docId: string) =>
    request<{ document: DocumentRecord; note: string }>(`/api/documents/${docId}`),

  saveDocumentNote: (docId: string, content: string) =>
    request<{ content: string }>(`/api/documents/${docId}/note`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }),
}

