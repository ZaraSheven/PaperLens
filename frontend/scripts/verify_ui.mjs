/**
 * 真机渲染检查：用本机 Edge 打开应用，验证锚点规则、气泡和公式原图。
 *
 * 前置条件：后端已在 127.0.0.1:8756 运行，并且库里至少有一份文献。
 * 运行：node scripts/verify_ui.mjs
 * 截图输出：../data/ui/*.png
 */
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const BASE = process.env.APP_URL ?? 'http://127.0.0.1:8756'
const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'data', 'ui')
mkdirSync(OUT, { recursive: true })

const failures = []
const check = (label, ok, extra = '') => {
  if (ok) {
    console.log(`  通过  ${label}`)
  } else {
    failures.push(label)
    console.log(`  失败  ${label} ${extra}`)
  }
}

const browser = await chromium.launch({ channel: 'msedge' })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

const ensureConfigured = async () => {
  await page.goto(BASE, { waitUntil: 'networkidle' })
  if (await page.locator('.setup').count()) {
    if (process.env.VERIFY_SETUP_CONFIG !== '1') {
      throw new Error('当前服务未配置模型；测试请使用 VERIFY_SETUP_CONFIG=1 和临时 .env')
    }
    const inputs = page.locator('.setup-section input')
    check('API Key 输入不触发密码管理器', (await inputs.nth(1).getAttribute('type')) === 'text')
    check('每个模型字段都有拉取按钮', (await page.locator('.model-picker button').count()) === 2)
    await inputs.nth(0).fill('http://127.0.0.1:8899/v1')
    await inputs.nth(1).fill('test-key')
    await inputs.nth(2).fill('fake-chat')
    await inputs.nth(3).fill('http://127.0.0.1:8899/v1')
    await inputs.nth(4).fill('test-key')
    await inputs.nth(5).fill('fake-translate')
    await page.locator('.setup-actions .primary').click()
    await page.waitForSelector('.library', { timeout: 10000 })
    check('模型配置页保存后进入文献库', true)
  }
}

const patchDocument = (docId, payload) =>
  page.evaluate(
    async ([id, patch]) => {
      const response = await fetch(`/api/documents/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      return response.json()
    },
    [docId, payload],
  )

const openDocumentById = async (docId, mode = 'double') => {
  await page.goto(BASE, { waitUntil: 'networkidle' })
  const card = page.locator(`[data-doc-id="${docId}"] .doc-open`)
  if (mode === 'single') await card.click()
  else await card.dblclick()
  await page.waitForSelector('.page canvas', { timeout: 20000 })
  await page.waitForTimeout(2500)
}

await ensureConfigured()

const documents = await page.evaluate(() => fetch('/api/documents').then((r) => r.json()))
let selected = null
for (let index = 0; index < documents.length; index += 1) {
  const candidateBlocks = await page.evaluate(
    (id) => fetch(`/api/documents/${id}/blocks`).then((r) => r.json()),
    documents[index].id,
  )
  const hasFormula = candidateBlocks.some((block) => block.kind === 'formula')
  const hasFigure = candidateBlocks.some((block) => block.kind === 'figure')
  const hasTable = candidateBlocks.some((block) => block.kind === 'table')
  const hasInline = candidateBlocks.some(
    (block) =>
      block.kind === 'text' && (block.segments ?? []).some((segment) => segment.kind === 'math'),
  )
  if (hasFormula && hasFigure && hasTable && hasInline) {
    selected = { docId: documents[index].id, blocks: candidateBlocks, document: documents[index] }
    break
  }
}

check('库里有可用于检查的完整文献', Boolean(selected), JSON.stringify(documents))
if (!selected) {
  await browser.close()
  process.exit(1)
}

const { docId, blocks } = selected
const formula = blocks.find((b) => b.kind === 'formula')
const figure = blocks.find((b) => b.kind === 'figure')
const table = blocks.find((b) => b.kind === 'table')
const inline = blocks.find(
  (b) => b.kind === 'text' && (b.segments ?? []).some((segment) => segment.kind === 'math'),
)
check('解析结果里有公式块', Boolean(formula))
check('解析结果里有图表块', Boolean(figure))
check('解析结果里有表格块', Boolean(table))
check('解析结果里有行内公式片段', Boolean(inline))
check(
  '实际文献里没有断词加空格残留',
  !blocks.some((block) => /[A-Za-z]+-\s+(?!(?:and|or)\b)[a-z]/.test(block.text)),
)
const numberedItems = blocks.filter((block) => /^\d+\.\s/.test(block.text))
check(
  '编号列表按项分开，不跨到下一项',
  numberedItems.length >= 3 &&
    !blocks.some(
      (block) => block.text.includes('1. We propose') && block.text.includes('2. We designed'),
    ),
  JSON.stringify(numberedItems.slice(0, 4).map((block) => block.text.slice(0, 40))),
)

console.log('\n论文列表详情')
await page.evaluate(
  () =>
    fetch('/api/categories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'UI测试分类' }),
    }),
)
await patchDocument(docId, { read_status: 'read', category: 'UI测试分类' })
await page.goto(BASE, { waitUntil: 'networkidle' })
const libraryState = await page.evaluate(
  (id) => ({
    columns: Array.from(document.querySelectorAll('.doc-column-head h2')).map(
      (item) => item.textContent,
    ),
    categorized: document
      .querySelector(`[data-doc-id="${id}"] .doc-meta`)
      ?.textContent?.includes('UI测试分类'),
  }),
  docId,
)
check(
  '文献库分成待读和已读两栏',
  libraryState.columns.includes('待读') && libraryState.columns.includes('已读'),
  JSON.stringify(libraryState),
)
check('文献分类显示在列表里', libraryState.categorized === true, JSON.stringify(libraryState))

console.log('\n分类文件夹')
const folderState = await page.evaluate((id) => {
  const columns = Array.from(document.querySelectorAll('.doc-column')).map((column) => ({
    title: column.querySelector('.doc-column-head h2')?.textContent ?? '',
    total: Number(column.querySelector('.doc-column-head span')?.textContent ?? 0),
    folders: Array.from(column.querySelectorAll('.folder')).map((folder) => ({
      name: folder.querySelector('.folder-name')?.textContent ?? '',
      count: folder.querySelectorAll('li[data-doc-id]').length,
    })),
  }))
  const owner = document
    .querySelector(`li[data-doc-id="${id}"]`)
    ?.closest('.folder')
    ?.querySelector('.folder-name')?.textContent
  return { columns, owner }
}, docId)
check(
  '两栏里各有一套分类文件夹',
  folderState.columns.length === 2 &&
    folderState.columns.every((item) => item.total === 0 || item.folders.length > 0),
  JSON.stringify(folderState.columns.map((item) => `${item.title}:${item.folders.length}`)),
)
check(
  '已读栏里有这个分类的文件夹',
  folderState.columns.some(
    (item) =>
      item.title === '已读' &&
      item.folders.some((folder) => folder.name === 'UI测试分类' && folder.count > 0),
  ),
  JSON.stringify(folderState.columns),
)
check('文献排在自己的分类文件夹里', folderState.owner === 'UI测试分类', String(folderState.owner))

const folderToggle = page.locator('[data-folder="read:UI测试分类"] .folder-head')
await folderToggle.click()
await page.waitForTimeout(200)
check(
  '文件夹可以收起来',
  (await page.locator(`li[data-doc-id="${docId}"]`).count()) === 0,
)
await folderToggle.click()
await page.waitForTimeout(200)
check('再点一次能展开', await page.locator(`li[data-doc-id="${docId}"]`).isVisible())

console.log('\n皮肤')
// 皮肤是用户自己的设置，跑完要放回去，不能把别人的选择留在「原味」上。
const previousAppearance = (
  await page.evaluate(() => fetch('/api/appearance').then((r) => r.json()))
).appearance
const skinList = await page.evaluate(() => fetch('/api/skins').then((r) => r.json()))
check(
  '内置皮肤都能列出来',
  skinList.skins.length >= 4 && skinList.skins.some((item) => item.id === 'ink-night'),
  JSON.stringify(skinList.skins.map((item) => item.id)),
)
await page.locator('.library-head button:has-text("皮肤")').click()
await page.waitForSelector('.skin-drawer', { timeout: 8000 })
check('皮肤抽屉里有缩略图', (await page.locator('.skin-drawer .skin-thumb').count()) >= 5)

const pickSkin = async (skinId) => {
  await page.locator(`[data-skin-id="${skinId}"] .skin-pick`).click()
  // 参数是即时生效、攒 400ms 再写库的，等它落盘再继续。
  await page.waitForTimeout(900)
}
await pickSkin('ink-night')
const skinState = await page.evaluate(() => {
  const root = document.documentElement
  const dropzone = document.querySelector('.dropzone')
  return {
    skin: root.dataset.skin ?? '',
    theme: root.dataset.theme ?? '',
    glass: root.dataset.skinGlass ?? '',
    wallpaper: getComputedStyle(document.querySelector('.wallpaper')).backgroundImage,
    blur: dropzone ? getComputedStyle(dropzone).backdropFilter : '',
    paper: getComputedStyle(root).getPropertyValue('--paper').trim(),
  }
})
check(
  '换皮肤后 html 写上了皮肤编号和明暗',
  skinState.skin === 'ink-night' && skinState.theme === 'dark',
  JSON.stringify(skinState),
)
check(
  '壁纸层真的铺上了这张图',
  skinState.wallpaper.includes('/api/skins/ink-night/cover'),
  skinState.wallpaper,
)
check('玻璃面板开了模糊', skinState.glass === 'on' && skinState.blur.includes('blur'), skinState.blur)
check(
  '换皮肤不改纸面颜色，PDF 还是白纸',
  skinState.paper.toLowerCase() === '#ffffff',
  skinState.paper,
)
await page.screenshot({ path: join(OUT, '6-skin-dark.png') })

// 主色可以单独改：不重新传图，也不换皮肤。
await page.locator('[data-accent="#d9903f"]').click()
// 同样要等攒起来的那次写库落盘，不然刷新会读回旧主色。
await page.waitForTimeout(900)
const accentState = await page.evaluate(() =>
  getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
)
check('可以单独换主色，不用重新传图', accentState.toLowerCase() === '#d9903f', accentState)

await page.reload({ waitUntil: 'networkidle' })
await page.waitForSelector('.library', { timeout: 10000 })
check(
  '刷新之后皮肤还在',
  (await page.evaluate(() => document.documentElement.dataset.skin)) === 'ink-night',
)

await page.locator('.library-head button:has-text("皮肤")').click()
await page.waitForSelector('.skin-drawer', { timeout: 8000 })
await pickSkin('plain')
const plainState = await page.evaluate(() => ({
  skin: document.documentElement.dataset.skin ?? '',
  wallpaper: getComputedStyle(document.querySelector('.wallpaper')).backgroundImage,
  inline: document.documentElement.getAttribute('style') ?? '',
}))
check(
  '点原味能干净地退回默认外观',
  plainState.skin === '' &&
    !plainState.wallpaper.includes('url') &&
    !plainState.inline.includes('--accent'),
  JSON.stringify(plainState),
)
await page.locator('.skin-head .icon').click()
await page.waitForSelector('.skin-drawer', { state: 'detached', timeout: 8000 })

await page.locator(`[data-doc-id="${docId}"] .doc-open`).click()
await page.waitForSelector('.details-modal', { timeout: 20000 })
await page.waitForSelector('.details-body', { timeout: 20000 })
const detailState = await page.evaluate(() => ({
  sections: Array.from(document.querySelectorAll('.details-body h3')).map((item) => item.textContent),
  summary: document.querySelector('.details-body section p')?.textContent ?? '',
  readerOpen: Boolean(document.querySelector('.reader')),
}))
check(
  '单击文献弹出论文详情',
  detailState.sections.includes('论文梗概') &&
    detailState.sections.includes('使用的方法') &&
    detailState.sections.includes('解决的问题') &&
    detailState.sections.includes('我的疑问和解答'),
  JSON.stringify(detailState),
)
check('详情里有论文梗概正文', detailState.summary.trim().length > 0, JSON.stringify(detailState))
check('单击详情不会直接进入阅读器', !detailState.readerOpen, JSON.stringify(detailState))
await page.screenshot({ path: join(OUT, '0-document-details.png') })
await page.locator('.details-modal .icon').click()

console.log('\n待读直接进入')
await patchDocument(docId, { read_status: 'unread' })
await page.goto(BASE, { waitUntil: 'networkidle' })
await page.locator(`[data-doc-id="${docId}"] .doc-open`).click()
await page.waitForSelector('.reader', { timeout: 10000 })
check('待读文献单击直接进入阅读器', true)
await page.locator('.toolbar button:has-text("返回")').click()
await page.waitForSelector('.library', { timeout: 10000 })

await patchDocument(docId, { read_status: 'read' })
await openDocumentById(docId)

console.log('\n主页面清晰度')
const pageDensity = await page.evaluate(() => {
  const canvas = document.querySelector('.page canvas')
  return {
    backing: canvas.width,
    css: canvas.getBoundingClientRect().width,
    ratio: window.devicePixelRatio || 1,
  }
})
check(
  'PDF 主页面至少按 2 倍像素密度渲染',
  pageDensity.css > 0 && pageDensity.backing / pageDensity.css >= 1.9,
  JSON.stringify(pageDensity),
)
const originalHref = await page.locator('.toolbar a:has-text("原文件")').getAttribute('href')
check(
  '原文件入口直接指向原始 PDF',
  originalHref === `/api/documents/${docId}/file`,
  String(originalHref),
)

console.log('\n页边锚点')
// 把鼠标挪到角落再测量，否则它停在某个段落上，那个段落的锚点会处于显形状态。
await page.mouse.move(4, 4)
await page.waitForTimeout(200)
const markerState = await page.evaluate(() => {
  const all = Array.from(document.querySelectorAll('.marker'))
  const ghost = all.filter((m) => m.classList.contains('is-ghost'))
  const visibleGhost = ghost.filter((m) => Number(getComputedStyle(m).opacity) > 0.05)
  return {
    total: all.length,
    flagged: document.querySelectorAll('.marker.is-flagged').length,
    ghost: ghost.length,
    visibleGhost: visibleGhost.length,
    blocks: document.querySelectorAll('.block-hit').length,
  }
})
check('每个段落都有锚点节点', markerState.total === markerState.blocks, JSON.stringify(markerState))
check('鼠标不在段落上时锚点全部隐藏', markerState.visibleGhost === 0, JSON.stringify(markerState))
const flaggedBefore = markerState.flagged

await page.locator('.block').first().hover()
await page.waitForTimeout(250)
const hoverVisible = await page.evaluate(() => {
  const marker = document.querySelector('.block:hover .marker')
  return marker ? Number(getComputedStyle(marker).opacity) : 0
})
check('鼠标移到段落上才出现锚点', hoverVisible > 0.2, String(hoverVisible))
await page.screenshot({ path: join(OUT, '1-clean-page.png') })

console.log('\n连续多选')
const firstPageBlocks = blocks.filter((block) => block.page === 0)
const selectionStart = firstPageBlocks[0]
const selectionEnd = firstPageBlocks[2]
await page.locator('.toolbar button:has-text("多选")').click()
await page.locator(`[data-block="${selectionStart.id}"]`).click()
await page.locator(`[data-block="${selectionEnd.id}"]`).click({ modifiers: ['Shift'] })
await page.waitForSelector('.selection-bar', { timeout: 5000 })
const selectionState = await page.evaluate(() => ({
  count: document.querySelectorAll('.block-hit.is-selected').length,
  label: document.querySelector('.selection-count')?.textContent ?? '',
}))
check('Shift 可以连续选中三块', selectionState.count === 3, JSON.stringify(selectionState))
check('选中操作栏显示数量', selectionState.label.includes('3'), JSON.stringify(selectionState))
await page.screenshot({ path: join(OUT, '1b-multi-select.png') })
await page.locator('.selection-bar button:has-text("清除")').click()
await page.locator('.toolbar button:has-text("多选")').click()

console.log('\n放大多选栏可见性')
await page.locator('.toolbar button:has-text("多选")').click()
for (let index = 0; index < 12; index += 1) {
  await page.locator('.zoom button').nth(1).click()
}
await page.waitForTimeout(700)
const selectionCount = Math.min(firstPageBlocks.length, 15)
await page.locator(`[data-block="${selectionStart.id}"]`).click()
for (let index = 1; index < selectionCount; index += 1) {
  await page
    .locator(`[data-block="${firstPageBlocks[index].id}"]`)
    .click({ modifiers: ['Shift'] })
}
await page.waitForSelector('.selection-bar', { timeout: 8000 })
const zoomedSelection = await page.evaluate(() => {
  const bar = document.querySelector('.selection-bar')
  const rect = bar.getBoundingClientRect()
  const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
  return {
    fullyVisible:
      rect.left >= 0 &&
      rect.top >= 0 &&
      rect.right <= window.innerWidth &&
      rect.bottom <= window.innerHeight,
    hitClass: typeof hit?.className === 'string' ? hit.className : '',
  }
})
check('300% 放大后选中栏仍完整可见', zoomedSelection.fullyVisible, JSON.stringify(zoomedSelection))
check(
  '选中栏处于最上层可点击',
  zoomedSelection.hitClass.includes('selection-bar'),
  JSON.stringify(zoomedSelection),
)
await page.screenshot({ path: join(OUT, '1c-multi-select-zoom.png') })
await page.locator('.selection-bar button:has-text("清除")').click()
await page.locator('.toolbar button:has-text("多选")').click()
for (let index = 0; index < 12; index += 1) {
  await page.locator('.zoom button').nth(0).click()
}

console.log('\n疑问标记')
// 挑一段本来没有笔记的，验证完再清回去，保证脚本可以反复运行。
const probeId = blocks.find((b) => b.kind === 'text' && !b.note).id
await page.evaluate(
  async (id) => {
    await fetch(`/api/blocks/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: '渲染检查留下的笔记' }),
    })
  },
  probeId,
)
await openDocumentById(docId)
const flagged = await page.evaluate(() => {
  const markers = Array.from(document.querySelectorAll('.marker.is-flagged'))
  return markers.map((m) => Number(getComputedStyle(m).opacity))
})
check('写过笔记的段落多出一个常驻标记', flagged.length === flaggedBefore + 1, JSON.stringify(flagged))
check('常驻标记是可见的', flagged.every((opacity) => opacity > 0.9), JSON.stringify(flagged))
await page.screenshot({ path: join(OUT, '2-flagged.png') })

console.log('\n提问标注与引用隐藏')
const questionProbe = blocks.find((b) => b.kind === 'text' && !b.note && b.message_count === 0)
await page.locator(`[data-block="${questionProbe.id}"]`).scrollIntoViewIfNeeded()
await page.waitForTimeout(700)
await page.locator(`[data-marker-block="${questionProbe.id}"]`).click()
await page.waitForSelector('.bubble', { state: 'visible', timeout: 8000 })
await page.locator('.bubble .bubble-tabs button:has-text("对话")').click()
await page.locator('.bubble .composer textarea').fill('引用格式测试')
await page.locator('.bubble .composer button:has-text("提问")').click()
// 这一步真的会调用对话模型。接假模型时是秒回，接真实厂商时一分钟以上也正常。
await page.waitForSelector('.bubble .message.role-assistant .message-text', { timeout: 180000 })
const questionState = await page.evaluate((id) => ({
  answer: document.querySelector('.bubble .message.role-assistant .message-text')?.textContent ?? '',
  citationNodes: document.querySelectorAll('.bubble .citation').length,
  questioned: document.querySelector(`[data-block="${id}"]`)?.classList.contains('is-questioned'),
  flagged: document
    .querySelector(`[data-marker-block="${id}"]`)
    ?.classList.contains('is-flagged'),
}), questionProbe.id)
check('提问后段落有疑问底色', questionState.questioned === true, JSON.stringify(questionState))
check('提问后页边留下疑问标记', questionState.flagged === true, JSON.stringify(questionState))
check(
  '回答里不再显示引用标记',
  questionState.citationNodes === 0 &&
    !/\[\s*(?:p)?\d+\s*\]/.test(questionState.answer),
  JSON.stringify(questionState),
)
await page.screenshot({ path: join(OUT, '2b-question-mark.png') })
if (await page.locator('.bubble .toggle input').isChecked()) {
  await page.locator('.bubble .toggle input').uncheck()
}
await page.keyboard.press('Escape')
await page.waitForTimeout(400)
await page.evaluate(
  async (id) => {
    await fetch(`/api/blocks/${id}/messages`, { method: 'DELETE' })
    await fetch(`/api/blocks/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: '' }),
    })
  },
  questionProbe.id,
)
await openDocumentById(docId)

console.log('\n公式气泡与原图')
// 先点一个靠后的公式，且不提前等待——这正是用户快速滚动后立刻点击的情形：
// 目标页面的画布可能还没画好。
const farFormula = blocks.filter((b) => b.kind === 'formula').at(-1)
await page.locator(`[data-marker-block="${farFormula.id}"]`).click()
await page.waitForSelector('.block-preview', { timeout: 8000 })
await page.waitForFunction(
  () => {
    const canvas = document.querySelector('.block-preview')
    if (!canvas || canvas.width < 40) return false
    const { data } = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height)
    for (let index = 0; index < data.length; index += 4) {
      if (data[index] < 235 || data[index + 1] < 235 || data[index + 2] < 235) return true
    }
    return false
  },
  null,
  { timeout: 15000 },
)
const farProbe = await page.evaluate(() => {
  const canvas = document.querySelector('.block-preview')
  return { backing: canvas.width, css: Math.round(canvas.getBoundingClientRect().width) }
})
check(
  '页面还没画好时点开，原图仍然裁得出来',
  farProbe.backing > 60,
  JSON.stringify(farProbe),
)
await page.keyboard.press('Escape')
await page.waitForTimeout(400)

await page.locator(`[data-block="${formula.id}"]`).scrollIntoViewIfNeeded()
await page.waitForTimeout(1200)
await page.locator(`[data-marker-block="${formula.id}"]`).click()
await page.waitForSelector('.bubble', { state: 'visible', timeout: 8000 })
await page.waitForTimeout(600)

const bubble = await page.evaluate(() => ({
  kind: document.querySelector('.bubble .kind-chip')?.textContent ?? '',
  hasPreview: Boolean(document.querySelector('.block-preview')),
  visibility: getComputedStyle(document.querySelector('.bubble')).visibility,
}))
check('气泡显示出来了', bubble.visibility === 'visible', JSON.stringify(bubble))
check('气泡标出这是公式', bubble.kind === '公式', JSON.stringify(bubble))
check('公式默认显示原图', bubble.hasPreview, JSON.stringify(bubble))

const preview = await page.evaluate(() => {
  const canvas = document.querySelector('.block-preview')
  if (!canvas || !canvas.width) return null
  const context = canvas.getContext('2d')
  const { data } = context.getImageData(0, 0, canvas.width, canvas.height)
  let ink = 0
  for (let index = 0; index < data.length; index += 4) {
    if (data[index] < 235 || data[index + 1] < 235 || data[index + 2] < 235) ink += 1
  }
  return { width: canvas.width, height: canvas.height, ink }
})
check('原图确实画出了内容而不是空白', Boolean(preview) && preview.ink > 50, JSON.stringify(preview))
await page.screenshot({ path: join(OUT, '3-formula-bubble.png') })

console.log('\n行内公式')
await page.keyboard.press('Escape')
await page.waitForTimeout(400)
await page.locator(`[data-block="${inline.id}"]`).scrollIntoViewIfNeeded()
await page.waitForTimeout(1200)
await page.locator(`[data-marker-block="${inline.id}"]`).click()
await page.waitForSelector('.bubble .inline-math', { state: 'visible', timeout: 10000 })
await page.waitForFunction(
  () => {
    const canvas = document.querySelector('.bubble .inline-math')
    if (!canvas || canvas.width < 4 || canvas.height < 4) return false
    const { data } = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height)
    for (let index = 0; index < data.length; index += 4) {
      if (data[index] < 235 || data[index + 1] < 235 || data[index + 2] < 235) return true
    }
    return false
  },
  null,
  { timeout: 15000 },
)
const inlineProbe = await page.evaluate(() => {
  const canvas = document.querySelector('.bubble .inline-math')
  return {
    count: document.querySelectorAll('.bubble .inline-math').length,
    backing: canvas.width,
    css: canvas.getBoundingClientRect().width,
  }
})
check('行内公式显示成原式图片', inlineProbe.count > 0 && inlineProbe.backing > 4, JSON.stringify(inlineProbe))
check(
  '行内公式按至少 2 倍像素密度绘制',
  inlineProbe.css > 0 && inlineProbe.backing / inlineProbe.css >= 1.9,
  JSON.stringify(inlineProbe),
)
await page.screenshot({ path: join(OUT, '3b-inline-formula.png') })

console.log('\n图表气泡')
await page.keyboard.press('Escape')
await page.waitForTimeout(300)
await page.locator(`[data-block="${figure.id}"]`).scrollIntoViewIfNeeded()
await page.waitForTimeout(1200)
await page.locator(`[data-marker-block="${figure.id}"]`).click()
await page.waitForSelector('.bubble', { state: 'visible', timeout: 8000 })
await page.waitForTimeout(600)
const figureBubble = await page.evaluate(() => ({
  kind: document.querySelector('.bubble .kind-chip')?.textContent ?? '',
  hasPreview: Boolean(document.querySelector('.block-preview')),
  head: document.querySelector('.bubble-head')?.textContent ?? '',
}))
check('图表气泡标出这是图表', figureBubble.kind === '图表', JSON.stringify(figureBubble))
check('图表默认显示原图', figureBubble.hasPreview, JSON.stringify(figureBubble))
const figurePreview = await page.evaluate(() => {
  const canvas = document.querySelector('.block-preview')
  return {
    backing: canvas.width,
    css: Math.round(canvas.getBoundingClientRect().width),
    ratio: window.devicePixelRatio || 1,
  }
})
check(
  '图表原图按至少 2 倍像素密度绘制',
  figurePreview.css > 0 && figurePreview.backing / figurePreview.css >= 1.9,
  JSON.stringify(figurePreview),
)
await page.screenshot({ path: join(OUT, '4-image-bubble.png') })

console.log('\n表格气泡')
await page.keyboard.press('Escape')
await page.waitForTimeout(300)
await page.locator(`[data-block="${table.id}"]`).scrollIntoViewIfNeeded()
await page.waitForTimeout(1200)
await page.locator(`[data-marker-block="${table.id}"]`).click()
await page.waitForSelector('.bubble', { state: 'visible', timeout: 8000 })
await page.waitForTimeout(600)
const tableBubble = await page.evaluate(() => ({
  kind: document.querySelector('.bubble .kind-chip')?.textContent ?? '',
  hasPreview: Boolean(document.querySelector('.block-preview')),
  hint: document.querySelector('.bubble .pane .empty')?.textContent ?? '',
}))
check('表格气泡标出这是表格', tableBubble.kind === '表格', JSON.stringify(tableBubble))
check('表格默认按整张原图显示', tableBubble.hasPreview, JSON.stringify(tableBubble))
await page.screenshot({ path: join(OUT, '4b-table-bubble.png') })

console.log('\n笔记面板与导出入口')
await page.keyboard.press('Escape')
await page.waitForTimeout(400)
await page.locator('.toolbar button:has-text("文献笔记")').click()
await page.waitForSelector('.doc-panel', { timeout: 8000 })
const exportHref = await page.locator('.doc-panel .link-button').getAttribute('href')
check(
  '导出按钮指向本文的阅读记录',
  exportHref === `/api/documents/${docId}/markdown`,
  String(exportHref),
)
await page.screenshot({ path: join(OUT, '5-note-panel.png') })

// 还原现场，免得下次运行读到这次留下的笔记。
await page.evaluate(
  async (id) => {
    await fetch(`/api/blocks/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: '' }),
    })
  },
  probeId,
)

// 皮肤也放回进来时的样子：脚本不该替用户决定用哪套。
await page.evaluate(
  (appearance) =>
    fetch('/api/appearance', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(appearance),
    }),
  previousAppearance,
)

await browser.close()

console.log()
if (failures.length) {
  console.log(`失败 ${failures.length} 项：${failures.join('；')}`)
  process.exit(1)
}
console.log('界面渲染检查全部通过')
