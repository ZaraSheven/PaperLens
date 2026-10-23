<div align="center">

# PaperLens

**A paragraph-anchored PDF reader for research papers.**
Translate, ask, and take notes on the exact paragraph you are stuck on. Optional wallpaper skinning included.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[中文说明](README.zh-CN.md) &nbsp;|&nbsp; English

</div>

<img src="docs/screenshots/reader.png" alt="PaperLens reader" width="820">

## What is this

Reading a long paper is rarely linear. You jump between a definition, the method that depends on it,
and the experiment that tests it. Most tools flatten the paper into one long scroll, so where you read,
where you got stuck, and what you asked are all lost.

PaperLens splits a paper into paragraphs and makes every paragraph a place you can come back to.
Click any block and a bubble opens next to it: read a translation, ask the assistant about that block
while it uses the whole paper as context, or have it turn the block into a reading note.
Everything is stored against that block in a local database, so it is still there next week.

## Screenshots

The library keeps unread and read papers in two columns, with categories acting as folders.

| Library | Paper details |
|---|---|
| <img src="docs/screenshots/library.png" alt="Library" width="460"> | <img src="docs/screenshots/document-details.png" alt="Paper details" width="460"> |

### Asking questions

For formulas, the bubble shows the original crop from the page before it answers.

<img src="docs/screenshots/formula-bubble.png" alt="Formula question" width="820">

For tables, headers and numbers stay together so the assistant can talk about the real figures.

<img src="docs/screenshots/table-bubble.png" alt="Table question" width="820">

For figures, the crop is sent to a vision-capable chat model along with your question.

<img src="docs/screenshots/figure-bubble.png" alt="Figure question" width="820">

### Skins and setup

One skin is one wallpaper plus a set of glass parameters. Toolbars, cards, bubbles and dialogs become
translucent panels floating over the image, while the PDF page stays white. Upload your own image and
the light/dark mode and accent color are derived from it.

<img src="docs/screenshots/skin-drawer.png" alt="Skin drawer" width="820">

The setup page holds the two model routes, plus `agent.md` (assistant persona and answering style)
and the note template.

<img src="docs/screenshots/agent-setup.png" alt="Model setup" width="820">

## Features

**Reading and parsing**

- Upload a PDF and get blocks with normalised coordinates; parsing results survive re-uploads
- Two-column reading order via XY-cut, with repeated headers, footers and garbled blocks removed
- Hyphenated line breaks are repaired: `simula-` + `tion` becomes `simulation`, `state-` + `of-the-art` keeps its hyphens
- Numbered and bulleted lists are split per item, so continuations stay with their own item
- Formula blocks, embedded images, vector figures and `Table N` captions are detected
- Pages render at 2x density or higher, and canvases are released once they leave the viewport

**Per-paragraph Q&A and notes**

- Ask about any block: the assistant uses the whole paper as context and always includes the block you clicked
- Figures, formulas and tables send their original crop to a vision-capable chat model (can be turned off in settings)
- The question appears immediately and the answer streams in over SSE
- Math in answers is typeset with KaTeX; Markdown lists and bold text render normally
- The bubble can be dragged by its title bar and stops following the paragraph afterwards
- Four note templates: standard reading note, method breakdown, question list, custom
- Auto-note on bubble close, optional
- Export the whole reading record (notes, questions, full Q&A) as Markdown

**Library**

- Unread and read columns; single click opens an unread paper, single click on a read paper shows details, double click continues reading
- Categories behave as folders inside both columns, collapsible, with the collapsed state kept locally
- Paper details are generated on demand and cached: summary, methods, problems, conclusion, plus your own Q&A

**Appearance**

- Seven built-in skins: rose dream, ink night, paper calm, moss calm, amber dusk, violet night, graphite
- Upload your own wallpaper; light/dark and accent color are derived from the image
- Accent color can be changed alone: colors sampled from the image, nine presets, or a color picker
- Glass blur, panel opacity, wallpaper darkening and reader backdrop are all sliders, with one-click reset
- Skins are stored with `data/`, and the first paint does not flash the default palette

## Quick start

### 1. Requirements

Python 3.11+ and Node.js 18+.

```bash
git clone https://github.com/ZaraSheven/PaperLens.git
cd PaperLens

python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt   # Windows
# .venv/bin/python -m pip install -r backend/requirements.txt     # macOS / Linux

cd frontend
npm install
npm run build
cd ..
```

### 2. Run

```bash
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8756 --app-dir backend   # Windows
# .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8756 --app-dir backend     # macOS / Linux
```

Open <http://127.0.0.1:8756>. On first launch you get a setup page. Fill in two
OpenAI-compatible routes and they are written to `.env`:

| Route | Used for |
|---|---|
| Chat model | Q&A, paper details, note generation; a "supports vision" toggle decides whether image crops are sent |
| Translation model | Paragraph translation only, independent from the chat model |

You can also `cp .env.example .env` and fill it in by hand. Model names can be pulled from
the upstream `/models` endpoint directly in the UI.

### 3. Optional: generate a sample paper

```bash
.venv/Scripts/python backend/tests/make_sample.py
```

This writes `samples/sample-paper.pdf`, a synthetic two-column paper useful for trying things out.

## Tech stack

| Layer | Stack | Role |
|---|---|---|
| Frontend | React + TypeScript + Vite | UI, bubble placement, reading state |
| PDF rendering | PDF.js | Draws pages to canvas; re-renders crops at high resolution |
| Backend | FastAPI | API and static hosting for the built frontend |
| Parsing | PyMuPDF + pdfplumber + wordninja + XY-cut | Paragraph regrouping, hyphen repair, figure and formula detection |
| Q&A | Local keyword retrieval + LLM | The anchored paragraph first, then keyword hits from the whole paper |
| Storage | SQLite | Blocks, translations, notes, conversations, paper notes |
| Models | OpenAI-compatible API | Chat model for Q&A and notes, translation model for translation |
| Math | react-markdown + KaTeX | Typesets `$...$` in answers |
| Skins | CSS variables + wallpaper + Pillow | Derives light/dark and accent from the image, then only CSS variables change |

## Project layout

```
PaperLens/
|- backend/
|  |- app/              API, parsing, retrieval, model calls, skins, SQLite
|  |  \- skins/         Built-in skins (wallpaper + parameters)
|  \- tests/            Self-checks and the fake model used in tests
|- frontend/
|  |- src/              React UI, bubbles, PDF rendering, skins
|  \- scripts/          UI rendering checks
|- docs/screenshots/    Screenshots used by this README
|- data/                Runtime data (database, uploaded PDFs, skins), not in the repo
|- ARCHITECTURE.md      Module responsibilities and key design decisions
\- CONTEXT.md           Current progress
```

## Data and backup

Runtime data lives in `data/`: `library.db`, uploaded PDFs, your own skins and `agent.md`.
Copy that directory to back everything up.

The server binds to `127.0.0.1` by default and has no authentication. If you change it to
`0.0.0.0` for LAN access, anyone on the network can read, delete or upload your papers and
spend your model quota. Add an authentication layer first if you need remote access.

## Model requirements

Both routes must speak the OpenAI API shape (`/chat/completions`, and `/models` for the picker).
Any compatible provider works. The chat model needs vision support only if you want to ask about
figures and formulas; otherwise turn the toggle off so those crops are not sent.

## Testing

<details>
<summary>Show test commands</summary>

```bash
# Parser self-check: reading order, coordinate ranges, stable IDs, header removal, garbled blocks
.venv/Scripts/python backend/tests/test_parser.py

# Retrieval self-check: context assembly, block type labels, empty figure blocks kept
.venv/Scripts/python backend/tests/test_rag.py

# Model flow self-check: translation, Q&A, streaming answers, notes, with a fake model
# No API key required
.venv/Scripts/python backend/tests/test_llm_flow.py

# API smoke test: requires the server on port 8756, restores the sample afterwards
.venv/Scripts/python backend/tests/smoke_api.py

# Frontend type check and build
cd frontend && npm run build

# UI rendering check with Edge; requires the server on port 8756
# When the upstream model is unavailable, start a fake-model instance first:
#   .venv/Scripts/python backend/tests/serve_fake_app.py --port 8765
#   cd frontend && APP_URL=http://127.0.0.1:8765 node scripts/verify_ui.mjs
cd frontend && node scripts/verify_ui.mjs
```

The backend self-checks and the API smoke test all run locally without a real provider.
The UI check opens a real browser.

</details>

## API overview

<details>
<summary>Show main endpoints</summary>

| Method | Path | Purpose |
|---|---|---|
| GET / PUT | `/api/config` | Read or save chat and translation routes |
| POST | `/api/config/models` | List model names from the upstream `/models` |
| POST | `/api/documents` | Upload a PDF and parse it into blocks |
| GET / PATCH / DELETE | `/api/documents/{id}` | Paper details, category, deletion |
| GET | `/api/documents/{id}/file` | Original PDF |
| GET | `/api/documents/{id}/blocks` | Blocks with coordinates and kinds |
| GET / PATCH | `/api/blocks/{id}` | Translation and note for one block |
| POST | `/api/blocks/{id}/translate` | Translate one block |
| POST | `/api/blocks/{id}/messages/stream` | Ask about one block, streamed over SSE |
| POST | `/api/documents/{id}/messages/stream` | Whole-paper chat, streamed over SSE |
| POST / PUT | `/api/documents/{id}/note` | Whole-paper note |
| GET | `/api/documents/{id}/markdown` | Export the reading record |
| GET / POST / DELETE | `/api/skins` | List, upload, delete skins |
| GET / PUT | `/api/appearance` | Current skin and appearance parameters |

</details>

## Development

<details>
<summary>Show development notes</summary>

The Vite dev server proxies API calls to port 8756:

```bash
cd frontend
npm run dev      # http://127.0.0.1:5173
```

Run `npm run build` after changing frontend sources, and restart uvicorn after changing backend
sources. Neither picks up changes on its own.

Module responsibilities, data flow and the reasoning behind the main decisions are in
[ARCHITECTURE.md](ARCHITECTURE.md).

</details>

## Roadmap

- [ ] OCR for scanned papers
- [ ] Library-wide retrieval and literature review

## Known limitations

- Scanned papers need OCR first; only PDFs with a text layer are supported today.
- No embeddings: whole-paper retrieval is keyword based, which is fine for most questions but
  insensitive to paraphrasing.
- Generating paper details calls the chat model, so the first click can be slower than the list.

## Acknowledgements

A round of research into similar projects is recorded in [ARCHITECTURE.md](ARCHITECTURE.md).
PaperLens does not depend on any of them.

- [Future-House/paper-qa](https://github.com/Future-House/paper-qa)
- [PDFMathTranslate](https://github.com/Byaidu/PDFMathTranslate)
- [windingwind/zotero-pdf-translate](https://github.com/windingwind/zotero-pdf-translate)
- Skin concept inspired by the [Codex-Dream-Skin](https://github.com/Fei-Away/Codex-Dream-Skin) family

## License

[MIT](LICENSE)