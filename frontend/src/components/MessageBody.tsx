import Markdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkMath from 'remark-math'

import 'katex/dist/katex.min.css'

interface Props {
  content: string
}

/**
 * 答案里不该再出现引用标记，但旧库里留着两种写法：检索片段序号 `[1]`、`[2]`，
 * 以及更早版本把页码当编号的 `[p1]`、`[p12]`。两种都在这里清掉。
 * 只认两三位以内的数字，避免把正文里的 `[2024]` 这种年份一起吃掉。
 */
const CITATION_TOKEN = /\[\s*p\s*\d{1,3}\s*\]|\[\s*\d{1,2}\s*\]/gi

/**
 * 回答按 Markdown 渲染，公式交给 KaTeX 排版。
 *
 * 模型输出的是 `$Z = f \cdot b / d$` 这种 LaTeX，纯文本摆出来根本没法看，
 * 排成数学公式才读得懂。HTML 默认不解析，模型写什么都不会变成页面结构。
 */
export function MessageBody({ content }: Props) {
  const text = content
    .replace(CITATION_TOKEN, '')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\s+([，。！？；：,.!?;:])/g, '$1')
    .trim()

  return (
    <div className="message-text">
      <Markdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
        {text}
      </Markdown>
    </div>
  )
}
