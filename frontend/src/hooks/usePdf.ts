import { useEffect, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

import type { PageSize } from '../types'

pdfjs.GlobalWorkerOptions.workerSrc = workerSrc

export function usePdf(url: string) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null)
  const [sizes, setSizes] = useState<PageSize[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    // 换文档时先清掉上一份的状态，否则新 PDF 还在加载时，旧的页面尺寸会和新的段落
    // 数据混在一起用。
    setDoc(null)
    setSizes([])
    setError(null)
    const task = pdfjs.getDocument(url)

    task.promise
      .then(async (loaded) => {
        const measured: PageSize[] = []
        for (let index = 1; index <= loaded.numPages; index += 1) {
          const page = await loaded.getPage(index)
          const viewport = page.getViewport({ scale: 1 })
          measured.push({ width: viewport.width, height: viewport.height })
        }
        if (cancelled) return
        setSizes(measured)
        setDoc(loaded)
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason))
      })

    return () => {
      cancelled = true
      void task.destroy()
    }
  }, [url])

  return { doc, sizes, error }
}

