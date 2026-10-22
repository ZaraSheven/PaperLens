/** 记住用户开关的偏好。存在浏览器本地，不跟文档走。 */

const AUTO_NOTE_KEY = 'paper-lens.auto-note'
const COLLAPSED_FOLDERS_KEY = 'paper-lens.collapsed-folders'

export function readAutoNote(): boolean {
  const raw = localStorage.getItem(AUTO_NOTE_KEY)
  return raw === null ? true : raw === '1'
}

export function writeAutoNote(value: boolean): void {
  localStorage.setItem(AUTO_NOTE_KEY, value ? '1' : '0')
}

/** 文献库里收起来的文件夹，key 形如 `unread:分类名`。 */
export function readCollapsedFolders(): Set<string> {
  const raw = localStorage.getItem(COLLAPSED_FOLDERS_KEY)
  if (!raw) return new Set()
  const parsed: unknown = JSON.parse(raw)
  if (!Array.isArray(parsed)) return new Set()
  return new Set(parsed.filter((item): item is string => typeof item === 'string'))
}

export function writeCollapsedFolders(keys: Set<string>): void {
  localStorage.setItem(COLLAPSED_FOLDERS_KEY, JSON.stringify(Array.from(keys)))
}
