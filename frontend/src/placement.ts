/**
 * 气泡定位：按「右 → 左 → 下 → 上」找第一个既在视口内、又不压住目标段落的位置。
 * 四个方向都放不下时贴着段落落位，再整体夹进视口。
 */

export type Placement = 'right' | 'left' | 'below' | 'above' | 'dock'

export interface Box {
  x: number
  y: number
  w: number
  h: number
}

export interface Placed {
  x: number
  y: number
  placement: Placement
}

const GAP = 12
const EDGE = 12
const OVERLAP_SLACK = 6

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

const inside = (x: number, y: number, w: number, h: number, viewport: { w: number; h: number }) =>
  x >= EDGE && y >= EDGE && x + w <= viewport.w - EDGE && y + h <= viewport.h - EDGE

const overlaps = (a: Box, b: Box) =>
  a.x < b.x + b.w - OVERLAP_SLACK &&
  a.x + a.w > b.x + OVERLAP_SLACK &&
  a.y < b.y + b.h - OVERLAP_SLACK &&
  a.y + a.h > b.y + OVERLAP_SLACK

export function placeBubble(
  anchor: Box,
  block: Box,
  bubble: { w: number; h: number },
  viewport: { w: number; h: number },
): Placed {
  // 纵向先夹进视口：段落可能很高（比如一整段正文），不夹的话上下两侧都会判成放不下，
  // 直接掉到兜底位置，看着就像气泡跑远了。
  const midY = clamp(
    anchor.y + anchor.h / 2 - bubble.h / 2,
    EDGE,
    Math.max(EDGE, viewport.h - bubble.h - EDGE),
  )
  const midX = anchor.x + anchor.w / 2 - bubble.w / 2

  const candidates: Placed[] = [
    { placement: 'right', x: anchor.x + anchor.w + GAP, y: midY },
    { placement: 'left', x: anchor.x - bubble.w - GAP, y: midY },
    { placement: 'below', x: midX, y: anchor.y + anchor.h + GAP },
    { placement: 'above', x: midX, y: anchor.y - bubble.h - GAP },
  ]

  for (const candidate of candidates) {
    if (!inside(candidate.x, candidate.y, bubble.w, bubble.h, viewport)) continue
    if (overlaps({ x: candidate.x, y: candidate.y, w: bubble.w, h: bubble.h }, block)) continue
    return candidate
  }

  // 四个方向都放不下时（例如窄屏上看一张跨栏大图），贴着段落在空间更大的一侧落位，
  // 再整体夹进视口。宁可压住一部分正文，也不要把气泡甩到离段落很远的地方。
  const roomRight = viewport.w - (anchor.x + anchor.w)
  const roomLeft = anchor.x
  const sideX =
    roomRight >= roomLeft ? anchor.x + anchor.w + GAP : anchor.x - bubble.w - GAP

  const below = anchor.y + anchor.h + GAP
  const above = anchor.y - bubble.h - GAP
  const stackY = below + bubble.h <= viewport.h - EDGE ? below : above >= EDGE ? above : anchor.y

  return {
    placement: 'dock',
    x: clamp(sideX, EDGE, Math.max(EDGE, viewport.w - bubble.w - EDGE)),
    y: clamp(stackY, EDGE, Math.max(EDGE, viewport.h - bubble.h - EDGE)),
  }
}

export const toBox = (rect: { left: number; top: number; width: number; height: number }): Box => ({
  x: rect.left,
  y: rect.top,
  w: rect.width,
  h: rect.height,
})

