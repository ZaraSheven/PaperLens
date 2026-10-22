/** text 是正文段落；formula、figure 和 table 的文字都抽不准，界面按原图显示。 */
export type BlockKind = 'text' | 'formula' | 'figure' | 'table'

export interface DocumentRecord {
  id: string
  filename: string
  title: string | null
  page_count: number
  block_count: number
  read_status: 'unread' | 'read'
  category: string
  created_at: string
}

export interface Block {
  id: string
  doc_id: string
  page: number
  kind: BlockKind
  order_index: number
  x0: number
  y0: number
  x1: number
  y1: number
  text: string
  /** 正文里的文字和行内公式片段；行内公式用页面原图显示。 */
  segments: InlineSegment[]
  translation: string | null
  note: string | null
  /** 这一段被问过几次。大于 0 表示这里曾经有疑问。 */
  message_count: number
  /** 有没有写过笔记。 */
  has_note: number
}

export interface InlineSegment {
  kind: 'text' | 'math'
  text: string
  x0: number
  y0: number
  x1: number
  y1: number
}

export interface Citation {
  block_id: string
  page: number
  text: string
}

export interface Message {
  id: number
  doc_id: string
  block_id: string | null
  /** 这问题是点着某一段问的（block），还是在整篇对话面板里问的（full）。 */
  scope: string
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  created_at: string
}

export interface PageSize {
  width: number
  height: number
}

/** 「疑问清单」里的一条：问过或记过笔记的段落。 */
export interface Question {
  id: string
  page: number
  order_index: number
  kind: BlockKind
  text: string
  note: string | null
  message_count: number
  first_question: string | null
}

export interface HealthStatus {
  chat: boolean
  translate: boolean
}

export interface ModelRouteConfig {
  base_url: string
  model: string
  api_key_set: boolean
}

export interface AppConfig {
  chat: ModelRouteConfig
  translate: ModelRouteConfig
  note_template: string
  agent_prompt: string
  /** 对话模型能不能看图：开着的话问图会把那一块的原图一起发给模型。 */
  chat_vision: boolean
}

export interface ConfigResponse {
  config: AppConfig
  health: HealthStatus
}

export interface ModelRouteInput {
  base_url: string
  model: string
  api_key: string | null
}

export interface ConfigInput {
  chat: ModelRouteInput
  translate: ModelRouteInput
  note_template?: string
  agent_prompt?: string
  chat_vision?: boolean
}

export interface ModelListInput {
  kind: 'chat' | 'translate'
  base_url: string
  api_key: string | null
}

export interface DocumentOverview {
  summary: string
  methods: string[]
  problems: string[]
  conclusion: string
}

export interface DocumentDetails {
  document: DocumentRecord
  overview: DocumentOverview
  questions: Array<{
    block: Question
    messages: Message[]
  }>
}

