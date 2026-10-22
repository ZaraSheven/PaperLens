import { useEffect, useState } from 'react'

import { api } from '../api'
import type { AppConfig, ConfigInput, ConfigResponse, ModelRouteConfig } from '../types'
import { errorMessage } from '../util'

interface Props {
  onSaved: (result: ConfigResponse) => void
  /** 已经配置过时允许返回文献库；首次配置不能跳过。 */
  onCancel?: () => void
}

interface FormRoute {
  base_url: string
  api_key: string
  model: string
}

const emptyRoute = (): FormRoute => ({ base_url: '', api_key: '', model: '' })

const NOTE_TEMPLATES = [
  {
    key: 'standard',
    label: '标准阅读笔记',
    value: `请根据下面内容整理阅读笔记，用简体中文，按这个结构输出 Markdown：
1. 这段讲了什么
2. 关键方法或结论
3. 我的疑问与解答

原文：
{原文}

问答：
{问答}

只依据给定内容，不要补充外部知识。`,
  },
  {
    key: 'methods',
    label: '方法与贡献拆解',
    value: `请根据下面内容整理方法笔记，用简体中文输出 Markdown：
1. 论文要解决的问题
2. 使用的核心方法
3. 相比已有方法的关键改动
4. 可以复用的思路

原文：
{原文}

问答：
{问答}`,
  },
  {
    key: 'questions',
    label: '疑问与结论清单',
    value: `请根据下面内容整理成问题清单，用简体中文输出 Markdown：
1. 我提出的问题
2. 原文给出的答案
3. 仍然没有解决的问题

原文：
{原文}

问答：
{问答}`,
  },
  { key: 'custom', label: '自定义模板', value: '' },
] as const

const DEFAULT_NOTE_TEMPLATE = NOTE_TEMPLATES[0].value
const DEFAULT_AGENT_PROMPT = `你是我的科研阅读助手。
回答时先给结论，再解释关键依据；术语保留英文原名；发现我没有问到但重要的限制时直接指出。`

const toForm = (route: ModelRouteConfig): FormRoute => ({
  base_url: route.base_url,
  api_key: '',
  model: route.model,
})

function RouteFields({
  kind,
  title,
  hint,
  route,
  hasKey,
  models,
  loading,
  onChange,
  onFetchModels,
}: {
  kind: 'chat' | 'translate'
  title: string
  hint: string
  route: FormRoute
  hasKey: boolean
  models: string[]
  loading: boolean
  onChange: (next: FormRoute) => void
  onFetchModels: () => void
}) {
  return (
    <section className="setup-section">
      <div className="setup-section-head">
        <h2>{title}</h2>
        <span className={hasKey ? 'setup-state ready' : 'setup-state'}>
          {hasKey ? '密钥已保存' : '等待配置'}
        </span>
      </div>
      <p className="setup-hint">{hint}</p>
      <label>
        <span>Base URL</span>
        <input
          value={route.base_url}
          onChange={(event) => onChange({ ...route, base_url: event.target.value })}
          placeholder="https://api.example.com/v1"
          autoComplete="off"
        />
      </label>
      <label>
        <span>API Key</span>
        <input
          type="text"
          value={route.api_key}
          onChange={(event) => onChange({ ...route, api_key: event.target.value })}
          placeholder={hasKey ? '已保存，留空则继续使用旧密钥' : 'sk-...'}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="none"
          spellCheck={false}
          data-lpignore="true"
          data-1p-ignore="true"
          data-form-type="other"
        />
      </label>
      <label>
        <span>模型名</span>
        <div className="model-picker">
          <input
            list={`model-options-${kind}`}
            value={route.model}
            onChange={(event) => onChange({ ...route, model: event.target.value })}
            placeholder="先拉取模型，或直接选择"
            autoComplete="off"
            spellCheck={false}
          />
          <datalist id={`model-options-${kind}`}>
            {models.map((model) => (
              <option key={model} value={model} />
            ))}
          </datalist>
          <button type="button" className="ghost" disabled={loading} onClick={onFetchModels}>
            {loading ? '拉取中…' : '拉取模型'}
          </button>
        </div>
      </label>
    </section>
  )
}

export function Setup({ onSaved, onCancel }: Props) {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [chat, setChat] = useState(emptyRoute)
  const [translate, setTranslate] = useState(emptyRoute)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [noteTemplate, setNoteTemplate] = useState<string>(DEFAULT_NOTE_TEMPLATE)
  const [agentPrompt, setAgentPrompt] = useState<string>(DEFAULT_AGENT_PROMPT)
  const [notePreset, setNotePreset] = useState('standard')
  const [fetching, setFetching] = useState<'chat' | 'translate' | null>(null)
  const [models, setModels] = useState<Record<'chat' | 'translate', string[]>>({
    chat: [],
    translate: [],
  })

  useEffect(() => {
    let cancelled = false
    api
      .config()
      .then((result) => {
        if (cancelled) return
        setConfig(result.config)
        setChat(toForm(result.config.chat))
        setTranslate(toForm(result.config.translate))
        const template = result.config.note_template || DEFAULT_NOTE_TEMPLATE
        setNoteTemplate(template)
        setNotePreset(
          NOTE_TEMPLATES.find((item) => item.key !== 'custom' && item.value === template)?.key ??
            'custom',
        )
        setAgentPrompt(result.config.agent_prompt || DEFAULT_AGENT_PROMPT)
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(errorMessage(reason))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const fetchModels = async (
    kind: 'chat' | 'translate',
    route: FormRoute,
  ) => {
    setFetching(kind)
    setError(null)
    try {
      const result = await api.listModels({
        kind,
        base_url: route.base_url.trim(),
        api_key: route.api_key.trim() || null,
      })
      setModels((current) => ({ ...current, [kind]: result.models }))
      if (!result.models.length) setError('这个服务没有返回可用模型')
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setFetching(null)
    }
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    const translateEmpty =
      !translate.base_url.trim() && !translate.model.trim() && !translate.api_key.trim()
    const payload: ConfigInput = {
      chat: {
        base_url: chat.base_url.trim(),
        model: chat.model.trim(),
        api_key: chat.api_key.trim() || null,
      },
      translate: {
        base_url: translate.base_url.trim(),
        model: translate.model.trim(),
        api_key: translateEmpty ? '' : translate.api_key.trim() || null,
      },
      note_template: noteTemplate.trim(),
      agent_prompt: agentPrompt.trim(),
    }
    try {
      onSaved(await api.saveConfig(payload))
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="setup">
      <header className="setup-head">
        <div>
          <span className="setup-kicker">PaperLens</span>
          <h1>配置模型</h1>
          <p>对话模型负责问答和笔记，翻译模型只负责翻译；两者都配置好才能进入文献库。</p>
        </div>
        {onCancel && (
          <button type="button" className="ghost" onClick={onCancel}>
            返回
          </button>
        )}
      </header>

      {error && (
        <div className="banner error">
          {error}
          <button type="button" className="ghost" onClick={() => setError(null)}>
            知道了
          </button>
        </div>
      )}

      <div className="setup-grid">
        <RouteFields
          kind="chat"
          title="对话模型"
          hint="负责问答和笔记整理。"
          route={chat}
          hasKey={config?.chat.api_key_set ?? false}
          models={models.chat}
          loading={fetching === 'chat'}
          onChange={setChat}
          onFetchModels={() => void fetchModels('chat', chat)}
        />
        <RouteFields
          kind="translate"
          title="翻译模型"
          hint="只负责论文翻译，不复用对话模型。"
          route={translate}
          hasKey={config?.translate.api_key_set ?? false}
          models={models.translate}
          loading={fetching === 'translate'}
          onChange={setTranslate}
          onFetchModels={() => void fetchModels('translate', translate)}
        />
      </div>

      <section className="setup-template">
        <div className="setup-section-head">
          <h2>Agent 设定</h2>
          <span className="setup-state">agent.md</span>
        </div>
        <p className="setup-hint">
          用 Markdown 写你希望模型遵循的身份、回答风格和关注重点；保存到本机 data/agent.md。
        </p>
        <textarea
          className="note-editor"
          value={agentPrompt}
          onChange={(event) => setAgentPrompt(event.target.value)}
          rows={7}
        />
      </section>

      <section className="setup-template">
        <div className="setup-section-head">
          <h2>笔记模板</h2>
          <select
            value={notePreset}
            onChange={(event) => {
              const preset = NOTE_TEMPLATES.find((item) => item.key === event.target.value)
              setNotePreset(event.target.value)
              if (preset && preset.key !== 'custom') setNoteTemplate(preset.value)
            }}
          >
            {NOTE_TEMPLATES.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
        <p className="setup-hint">
          可用占位符：<code>{'{原文}'}</code> 和 <code>{'{问答}'}</code>。编辑内容后会自动视为自定义模板。
        </p>
        <textarea
          className="note-editor"
          value={noteTemplate}
          onChange={(event) => {
            setNoteTemplate(event.target.value)
            setNotePreset('custom')
          }}
          rows={7}
        />
      </section>

      <footer className="setup-actions">
        <span className="setup-note">密钥只写入本机 .env，接口不会回显。</span>
        <button type="button" className="primary" disabled={saving} onClick={() => void save()}>
          {saving ? '正在测试连接…' : '保存并进入'}
        </button>
      </footer>
    </div>
  )
}
