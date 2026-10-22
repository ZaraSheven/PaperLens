import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from './api'
import { Library } from './components/Library'
import { Reader } from './components/Reader'
import { Setup } from './components/Setup'
import {
  applyAppearance,
  defaultAppearance,
  PLAIN_SKIN,
  type Appearance,
  type Skin,
} from './skins'
import type { HealthStatus } from './types'
import { errorMessage } from './util'

export function App() {
  const [docId, setDocId] = useState<string | null>(null)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [configOpen, setConfigOpen] = useState(false)
  const [skins, setSkins] = useState<Skin[]>([PLAIN_SKIN])
  const [appearance, setAppearance] = useState<Appearance>(() => defaultAppearance(PLAIN_SKIN))
  const [skinError, setSkinError] = useState<string | null>(null)
  const saveTimer = useRef<number | null>(null)

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setHealth(null))
  }, [])

  // 外观和模型配置是两条独立的线：模型没配也能先把皮肤读回来。
  useEffect(() => {
    let cancelled = false
    Promise.all([api.skins(), api.appearance()])
      .then(([skinList, current]) => {
        if (cancelled) return
        setSkins(skinList.skins)
        setAppearance(current.appearance)
        const active =
          skinList.skins.find((item) => item.id === current.appearance.skin) ?? skinList.skins[0]
        applyAppearance(active, current.appearance)
      })
      .catch((reason: unknown) => {
        if (!cancelled) setSkinError(`外观没读回来：${errorMessage(reason)}`)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(
    () => () => {
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current)
    },
    [],
  )

  /** 改皮肤即时生效，写库攒一下再发：拖滑块会连着来几十次。 */
  const changeAppearance = useCallback(
    (next: Appearance) => {
      setAppearance(next)
      const active = skins.find((item) => item.id === next.skin)
      if (active) applyAppearance(active, next)
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current)
      saveTimer.current = window.setTimeout(() => {
        saveTimer.current = null
        api
          .saveAppearance(next)
          .catch((reason: unknown) => setSkinError(`外观没保存上：${errorMessage(reason)}`))
      }, 400)
    },
    [skins],
  )

  const ready = Boolean(health?.chat && health?.translate)

  return (
    <>
      {/* 壁纸层固定在最底下；原味皮肤的 --wallpaper 是 none，这一层等于不存在。 */}
      <div className="wallpaper" aria-hidden="true" />
      <div className="app">
        {skinError && (
          <div className="banner error">
            {skinError}
            <button type="button" className="ghost" onClick={() => setSkinError(null)}>
              知道了
            </button>
          </div>
        )}
        {!ready || configOpen ? (
          <Setup
            onSaved={(result) => {
              setHealth(result.health)
              setConfigOpen(false)
            }}
            onCancel={ready ? () => setConfigOpen(false) : undefined}
          />
        ) : docId ? (
          <Reader docId={docId} onBack={() => setDocId(null)} />
        ) : (
          <Library
            onOpen={setDocId}
            onConfigure={() => setConfigOpen(true)}
            skins={skins}
            appearance={appearance}
            onSkins={setSkins}
            onAppearance={changeAppearance}
          />
        )}
      </div>
    </>
  )
}
