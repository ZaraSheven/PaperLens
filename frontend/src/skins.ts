/**
 * 皮肤：一套皮肤 = 一张壁纸 + 一组参数。
 *
 * 后端只负责「这张图偏亮还是偏暗、主色是什么」，界面上的颜色在这里派生：
 * 面、字、线都按明暗算，强调色跟着图走。皮肤本身不写死一整套色板，
 * 所以用户丢一张图进来就能立刻成套。
 */

export interface Skin {
  id: string
  name: string
  builtin: boolean
  /** 壁纸文件名；空字符串表示没有壁纸（原味） */
  cover: string
  /** 图片算出来的明暗：图偏暗就该用亮字 */
  mode: 'light' | 'dark' | 'system'
  accent: string
  palette: string[]
  blur: number
  panel_opacity: number
  mask: number
  wallpaper_blur: number
  reader_shade: number
}

export interface Appearance {
  skin: string
  /** system = 跟着图（没有图时跟着系统） */
  mode: 'system' | 'light' | 'dark'
  /** 空字符串表示用皮肤自己的主色 */
  accent: string
  blur: number
  panel_opacity: number
  mask: number
  wallpaper_blur: number
  reader_shade: number
}

/** 这些变量是皮肤写上去的，切回原味时要一个个撤掉。 */
const SKIN_VARS = [
  '--wallpaper',
  '--wallpaper-mask',
  '--wallpaper-blur',
  '--wallpaper-opacity',
  '--glass-blur',
  '--glass-bg',
  '--glass-border',
  '--reader-bg',
  '--bg',
  '--panel',
  '--ink',
  '--muted',
  '--on-accent',
  '--line',
  '--line-strong',
  '--accent',
  '--accent-soft',
  '--accent-selected',
  '--question',
  '--question-soft',
  '--danger',
  '--danger-soft',
  '--tint',
  '--tint-strong',
  '--skeleton-a',
  '--skeleton-b',
  '--shadow-1',
  '--shadow-2',
  '--shadow-3',
  '--shadow-panel',
  '--scrim',
] as const

const CACHE_KEY = 'paper-lens.appearance'
export const PLAIN_ID = 'plain'

/** 皮肤列表还没读回来时先用它顶着，界面不至于空一块。 */
export const PLAIN_SKIN: Skin = {
  id: PLAIN_ID,
  name: '原味',
  builtin: true,
  cover: '',
  mode: 'system',
  accent: '',
  palette: [],
  blur: 0,
  panel_opacity: 1,
  mask: 0,
  wallpaper_blur: 0,
  reader_shade: 0,
}

/**
 * 常用主色。皮肤自带的主色不一定合口味，图里算出来的颜色又常常偏灰，
 * 所以给一排挑得出来的颜色，外加一个任意取色的入口。
 */
export const ACCENT_PRESETS: { name: string; value: string }[] = [
  { name: '朱砂', value: '#c0392b' },
  { name: '琥珀', value: '#d9903f' },
  { name: '苔绿', value: '#4a7c59' },
  { name: '松青', value: '#2f7f7a' },
  { name: '海蓝', value: '#3d7fb5' },
  { name: '靛蓝', value: '#4c5fd7' },
  { name: '紫罗兰', value: '#a97ce0' },
  { name: '玫红', value: '#c86b93' },
  { name: '石墨', value: '#7f8b99' },
]

export function defaultAppearance(skin?: Skin): Appearance {
  return {
    skin: skin?.id ?? PLAIN_ID,
    mode: 'system',
    accent: '',
    blur: skin?.blur ?? 0,
    panel_opacity: skin?.panel_opacity ?? 1,
    mask: skin?.mask ?? 0,
    wallpaper_blur: skin?.wallpaper_blur ?? 0,
    reader_shade: skin?.reader_shade ?? 0,
  }
}

function systemDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** 明暗怎么定：原味跟随系统；有图时默认跟随图，也可以手动钉住。 */
export function resolveTheme(skin: Skin, appearance: Appearance): 'light' | 'dark' {
  if (appearance.mode === 'light' || appearance.mode === 'dark') return appearance.mode
  if (skin.id === PLAIN_ID) return systemDark() ? 'dark' : 'light'
  return skin.mode === 'dark' ? 'dark' : 'light'
}

function hexToRgb(hex: string): [number, number, number] | null {
  const value = hex.trim().replace('#', '')
  if (!/^[0-9a-fA-F]{6}$/.test(value)) return null
  return [
    parseInt(value.slice(0, 2), 16),
    parseInt(value.slice(2, 4), 16),
    parseInt(value.slice(4, 6), 16),
  ]
}

function rgba(hex: string, alpha: number): string {
  const rgb = hexToRgb(hex)
  if (!rgb) return hex
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`
}

function luminance(hex: string): number {
  const rgb = hexToRgb(hex)
  if (!rgb) return 0
  return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
}

/**
 * 按明暗和参数算出这一套皮肤要用的一组变量。
 * 只有一个 accent 是「有颜色」的，其余都从明暗推，避免色板互相打架。
 */
export function skinVars(skin: Skin, appearance: Appearance): Record<string, string> {
  const theme = resolveTheme(skin, appearance)
  const dark = theme === 'dark'
  const accent = appearance.accent || skin.accent || (dark ? '#7aa7e0' : '#2b6cb0')
  const question = dark ? '#e0a33c' : '#c2710c'
  const panelRgb = dark ? '18, 20, 26' : '255, 255, 255'
  const maskRgb = dark ? '6, 8, 12' : '255, 255, 255'

  return {
    '--wallpaper': skin.cover ? `url("/api/skins/${skin.id}/cover")` : 'none',
    '--wallpaper-mask': `rgba(${maskRgb}, ${appearance.mask})`,
    '--wallpaper-blur': `${appearance.wallpaper_blur}px`,
    '--wallpaper-opacity': '1',
    '--glass-blur': `${appearance.blur}px`,
    '--glass-bg': `rgba(${panelRgb}, ${appearance.panel_opacity})`,
    '--glass-border': dark ? 'rgba(255, 255, 255, 0.18)' : 'rgba(255, 255, 255, 0.55)',
    '--reader-bg': dark
      ? `rgba(0, 0, 0, ${appearance.reader_shade})`
      : `rgba(120, 128, 145, ${appearance.reader_shade})`,
    '--bg': dark ? '#12141a' : '#e9e7e3',
    '--panel': `rgba(${panelRgb}, ${appearance.panel_opacity})`,
    '--ink': dark ? '#f2f4f8' : '#1b1d22',
    '--muted': dark ? 'rgba(242, 244, 248, 0.72)' : 'rgba(27, 29, 34, 0.66)',
    // 主色偏亮时用深字，否则白字，按钮上的文字才不会糊。
    '--on-accent': luminance(accent) > 0.62 ? '#101318' : '#ffffff',
    '--line': dark ? 'rgba(255, 255, 255, 0.16)' : 'rgba(24, 28, 40, 0.16)',
    '--line-strong': dark ? 'rgba(255, 255, 255, 0.28)' : 'rgba(24, 28, 40, 0.3)',
    '--accent': accent,
    '--accent-soft': rgba(accent, dark ? 0.22 : 0.16),
    '--accent-selected': rgba(accent, dark ? 0.34 : 0.24),
    '--question': question,
    '--question-soft': rgba(question, dark ? 0.24 : 0.18),
    '--danger': dark ? '#f0938a' : '#b42318',
    '--danger-soft': dark ? 'rgba(240, 147, 138, 0.18)' : 'rgba(180, 35, 24, 0.1)',
    '--tint': dark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(20, 24, 40, 0.06)',
    '--tint-strong': dark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(20, 24, 40, 0.1)',
    '--skeleton-a': dark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(255, 255, 255, 0.6)',
    '--skeleton-b': dark ? 'rgba(255, 255, 255, 0.09)' : 'rgba(20, 24, 40, 0.06)',
    '--shadow-1': dark ? '0 1px 3px rgba(0, 0, 0, 0.5)' : '0 1px 3px rgba(16, 24, 40, 0.16)',
    '--shadow-2': dark ? '0 12px 32px rgba(0, 0, 0, 0.5)' : '0 12px 32px rgba(16, 24, 40, 0.2)',
    '--shadow-3': dark ? '0 24px 60px rgba(0, 0, 0, 0.55)' : '0 24px 60px rgba(16, 24, 40, 0.26)',
    '--shadow-panel': dark
      ? '-8px 0 24px rgba(0, 0, 0, 0.45)'
      : '-8px 0 24px rgba(16, 24, 40, 0.12)',
    '--scrim': dark ? 'rgba(0, 0, 0, 0.55)' : 'rgba(16, 24, 40, 0.35)',
  }
}

/** 把当前皮肤写到 `<html>` 上，并缓存一份给下次首屏用。 */
export function applyAppearance(skin: Skin, appearance: Appearance): void {
  const root = document.documentElement
  const theme = resolveTheme(skin, appearance)
  const glass = appearance.blur > 0 && skin.id !== PLAIN_ID

  if (skin.id === PLAIN_ID) {
    root.removeAttribute('data-skin')
    root.removeAttribute('data-skin-glass')
    for (const name of SKIN_VARS) root.style.removeProperty(name)
  }
  root.setAttribute('data-theme', theme)

  const vars = skin.id === PLAIN_ID ? {} : skinVars(skin, appearance)
  if (skin.id !== PLAIN_ID) {
    root.setAttribute('data-skin', skin.id)
    if (glass) root.setAttribute('data-skin-glass', 'on')
    else root.removeAttribute('data-skin-glass')
    for (const [name, value] of Object.entries(vars)) root.style.setProperty(name, value)
  }

  // 缓存给 index.html 里的首屏脚本用，字段名要和那边保持一致。
  const cached: CachedAppearance = {
    theme,
    skin: skin.id,
    glass: glass ? 'on' : '',
    vars,
  }
  localStorage.setItem(CACHE_KEY, JSON.stringify(cached))
}

/** index.html 首屏脚本读的就是这个结构。 */
interface CachedAppearance {
  theme: string
  skin: string
  glass: string
  vars: Record<string, string>
}
