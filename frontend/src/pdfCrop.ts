import type { PDFDocumentProxy } from 'pdfjs-dist'

import type { PageSize } from './types'

/**
 * 气泡里的原图和行内公式都从这条高分辨率页面画布里裁。
 *
 * 不直接拿主页面已经画好的 canvas：主页面按屏幕像素比渲染，碰到宽图或缩放后
 * 再被压缩，字就会发虚。这里一次画出当前页的高清版本，所有片段共用。
 */
export function previewRenderScale(displayScale: number): number {
  const ratio = Math.max(window.devicePixelRatio || 1, 2)
  return Math.min(4, Math.max(2, displayScale * ratio))
}

export async function renderPageSurface(
  pdf: PDFDocumentProxy,
  pageIndex: number,
  scale: number,
): Promise<HTMLCanvasElement> {
  const page = await pdf.getPage(pageIndex + 1)
  const viewport = page.getViewport({ scale })
  const surface = document.createElement('canvas')
  surface.width = Math.ceil(viewport.width)
  surface.height = Math.ceil(viewport.height)
  const context = surface.getContext('2d')
  if (!context) throw new Error('无法创建页面画布')

  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, surface.width, surface.height)
  await page.render({ canvasContext: context, viewport }).promise
  return surface
}

interface CropBox {
  x0: number
  y0: number
  x1: number
  y1: number
}

/**
 * 从高清页面画布裁一小块，按当前阅读缩放显示。
 *
 * 画布 backing store 永远保留原图尺寸，显示尺寸才跟着阅读缩放走。
 * 气泡放不下时由外层横向滚动，不再为了塞进气泡而压小图片。
 */
export function drawCrop(
  target: HTMLCanvasElement,
  surface: HTMLCanvasElement,
  box: CropBox,
  pageSize: PageSize,
  displayScale: number,
  pad = 0,
): void {
  const padX = pad / pageSize.width
  const padY = pad / pageSize.height
  const x0 = Math.max(0, box.x0 - padX)
  const y0 = Math.max(0, box.y0 - padY)
  const x1 = Math.min(1, box.x1 + padX)
  const y1 = Math.min(1, box.y1 + padY)

  const sx = x0 * surface.width
  const sy = y0 * surface.height
  const sw = Math.max(1, (x1 - x0) * surface.width)
  const sh = Math.max(1, (y1 - y0) * surface.height)

  target.width = Math.round(sw)
  target.height = Math.round(sh)
  target.style.width = `${(x1 - x0) * pageSize.width * displayScale}px`
  target.style.height = `${(y1 - y0) * pageSize.height * displayScale}px`

  const context = target.getContext('2d')
  if (!context) return
  context.clearRect(0, 0, target.width, target.height)
  context.drawImage(surface, sx, sy, sw, sh, 0, 0, target.width, target.height)
}
