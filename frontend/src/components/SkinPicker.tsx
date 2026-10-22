import { useRef, useState } from 'react'

import { api } from '../api'
import {
  ACCENT_PRESETS,
  defaultAppearance,
  PLAIN_ID,
  type Appearance,
  type Skin,
} from '../skins'
import { errorMessage } from '../util'

interface Props {
  skins: Skin[]
  appearance: Appearance
  onSkins: (skins: Skin[]) => void
  onChange: (appearance: Appearance) => void
  onClose: () => void
  onError: (message: string) => void
}

/**
 * 换肤抽屉。
 *
 * 参数改动即时生效、即时写库，没有「保存」按钮：皮肤是拿来看的，不是拿来提交的。
 */
export function SkinPicker({
  skins,
  appearance,
  onSkins,
  onChange,
  onClose,
  onError,
}: Props) {
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const current = skins.find((item) => item.id === appearance.skin)
  const usingSkin = current !== undefined && current.id !== PLAIN_ID

  const pick = (skin: Skin) => {
    // 换皮肤时把参数换成这套皮肤自己的默认值，别把上一套的数字带过来。
    onChange({ ...defaultAppearance(skin), mode: appearance.mode })
  }

  const patch = (fields: Partial<Appearance>) => onChange({ ...appearance, ...fields })

  const upload = async (file: File) => {
    setBusy(true)
    try {
      const name = file.name.replace(/\.[^.]+$/, '')
      const result = await api.uploadSkin(name, file)
      const list = await api.skins()
      onSkins(list.skins)
      onChange({ ...defaultAppearance(result.skin), mode: appearance.mode })
    } catch (reason) {
      onError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (skin: Skin) => {
    if (!window.confirm(`删掉皮肤「${skin.name}」？`)) return
    try {
      await api.deleteSkin(skin.id)
      const list = await api.skins()
      onSkins(list.skins)
      if (appearance.skin === skin.id) onChange(defaultAppearance(list.skins[0]))
    } catch (reason) {
      onError(errorMessage(reason))
    }
  }

  return (
    <div className="skin-overlay" onClick={onClose}>
      <aside className="skin-drawer" onClick={(event) => event.stopPropagation()}>
        <header className="skin-head">
          <h2>皮肤</h2>
          <button type="button" className="icon" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </header>

        <div className="skin-grid">
          {skins.map((skin) => (
            <div
              key={skin.id}
              className={skin.id === appearance.skin ? 'skin-card is-active' : 'skin-card'}
              data-skin-id={skin.id}
            >
              <button type="button" className="skin-pick" onClick={() => pick(skin)}>
                {skin.cover ? (
                  <span
                    className="skin-thumb"
                    style={{ backgroundImage: `url("/api/skins/${skin.id}/cover")` }}
                  />
                ) : (
                  <span className="skin-thumb is-plain" />
                )}
                <span className="skin-name">{skin.name}</span>
              </button>
              {!skin.builtin && (
                <button
                  type="button"
                  className="icon skin-remove"
                  title="删掉这套皮肤"
                  aria-label={`删掉 ${skin.name}`}
                  onClick={() => void remove(skin)}
                >
                  ✕
                </button>
              )}
            </div>
          ))}

          <div className="skin-card">
            <button
              type="button"
              className="skin-pick"
              disabled={busy}
              onClick={() => inputRef.current?.click()}
            >
              <span className="skin-thumb is-upload">＋</span>
              <span className="skin-name">{busy ? '处理中…' : '用自己的图'}</span>
            </button>
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void upload(file)
                event.target.value = ''
              }}
            />
          </div>
        </div>

        {usingSkin && current && (
          <div className="skin-params">
            <label className="skin-row">
              <span>明暗</span>
              <select
                value={appearance.mode}
                onChange={(event) =>
                  patch({ mode: event.target.value as Appearance['mode'] })
                }
              >
                <option value="system">跟图</option>
                <option value="light">亮</option>
                <option value="dark">暗</option>
              </select>
            </label>

            <label className="skin-row">
              <span>玻璃模糊 {Math.round(appearance.blur)}</span>
              <input
                type="range"
                min={0}
                max={40}
                step={1}
                value={appearance.blur}
                onChange={(event) => patch({ blur: Number(event.target.value) })}
              />
            </label>

            <label className="skin-row">
              <span>面板不透明 {Math.round(appearance.panel_opacity * 100)}%</span>
              <input
                type="range"
                min={0.2}
                max={1}
                step={0.02}
                value={appearance.panel_opacity}
                onChange={(event) => patch({ panel_opacity: Number(event.target.value) })}
              />
            </label>

            <label className="skin-row">
              <span>压暗壁纸 {Math.round(appearance.mask * 100)}%</span>
              <input
                type="range"
                min={0}
                max={0.9}
                step={0.05}
                value={appearance.mask}
                onChange={(event) => patch({ mask: Number(event.target.value) })}
              />
            </label>

            <label className="skin-row">
              <span>壁纸虚化 {Math.round(appearance.wallpaper_blur)}</span>
              <input
                type="range"
                min={0}
                max={30}
                step={1}
                value={appearance.wallpaper_blur}
                onChange={(event) => patch({ wallpaper_blur: Number(event.target.value) })}
              />
            </label>

            <label className="skin-row" title="阅读区里纸面周围的暗度，压暗一点看白纸更舒服">
              <span>阅读台面 {Math.round(appearance.reader_shade * 100)}%</span>
              <input
                type="range"
                min={0}
                max={0.9}
                step={0.05}
                value={appearance.reader_shade}
                onChange={(event) => patch({ reader_shade: Number(event.target.value) })}
              />
            </label>

            <div className="skin-row skin-colors">
              <span>主色（取自这张图）</span>
              <div className="skin-swatches">
                {[current.accent, ...current.palette]
                  .filter((color, index, list) => color && list.indexOf(color) === index)
                  .map((color) => (
                    <button
                      key={color}
                      type="button"
                      className={
                        (appearance.accent || current.accent).toLowerCase() === color.toLowerCase()
                          ? 'skin-swatch is-active'
                          : 'skin-swatch'
                      }
                      style={{ background: color }}
                      title={color}
                      aria-label={`主色 ${color}`}
                      onClick={() => patch({ accent: color })}
                    />
                  ))}
              </div>
            </div>

            <div className="skin-row skin-colors">
              <span>主色（常用）</span>
              <div className="skin-swatches">
                {ACCENT_PRESETS.map((preset) => (
                  <button
                    key={preset.value}
                    type="button"
                    data-accent={preset.value}
                    className={
                      appearance.accent.toLowerCase() === preset.value
                        ? 'skin-swatch is-active'
                        : 'skin-swatch'
                    }
                    style={{ background: preset.value }}
                    title={preset.name}
                    aria-label={`主色 ${preset.name}`}
                    onClick={() => patch({ accent: preset.value })}
                  />
                ))}
                <label className="skin-swatch is-custom" title="自己取一个颜色">
                  <input
                    type="color"
                    value={appearance.accent || current.accent}
                    onChange={(event) => patch({ accent: event.target.value })}
                  />
                </label>
              </div>
            </div>
          </div>
        )}

        <p className="skin-note">
          皮肤跟着 data 目录一起备份；点「原味」随时回到默认外观。
        </p>
      </aside>
    </div>
  )
}
