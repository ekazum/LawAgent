# LawAgent

Web-based legal assistant for Israeli employment law.

## Project structure

- `backend/main.py` - FastAPI backend with Claude (Anthropic) + legal retrieval tool.
- `backend/requirements.txt` - Backend dependencies.
- `frontend/` - React + TypeScript UI (Vite).
- `docker-compose.yml` - Postgres + pgvector for the knowledge base.

## Run with Docker (recommended)

```powershell
copy .env.example .env   # then put your ANTHROPIC_API_KEY in .env
docker compose up -d --build
```

Open http://localhost:8000 — the backend container serves both the UI and the
API. The stack (app + database) restarts automatically after reboots.
The first build takes several minutes (PyTorch + the embedding model are baked
into the image, ~3GB).

## Run in development mode

### 1. Database (Postgres + pgvector)

```powershell
docker compose up -d
```

Starts Postgres 17 with the pgvector extension on port 5432 (user/password/db:
`lawagent`). The backend creates the schema automatically on startup.

### 2. Backend (FastAPI)

```powershell
cd backend
pip install -r requirements.txt
$env:ANTHROPIC_API_KEY = "your_key"
uvicorn main:app --host 127.0.0.1 --port 8000
```

Environment variables:

- `ANTHROPIC_API_KEY` - Anthropic API key used for chat (model: `claude-haiku-4-5`).
  If unset, each chat request must supply an `X-API-Key` header (the UI has a
  field for this). Document upload needs no API key — embeddings run locally.
- `DATABASE_URL` - Postgres connection string. Defaults to the docker-compose
  database (`postgresql://lawagent:lawagent@127.0.0.1:5432/lawagent`).
- `CORS_ORIGINS` - Comma-separated list of allowed browser origins.
  Defaults to the Vite dev server (`http://localhost:5173,http://127.0.0.1:5173`).

## Knowledge base (RAG)

The agent grounds its answers in documents uploaded in advance via the
"מאגר ידע" tab: guidelines (הנחיות), example documents (מסמכים לדוגמה), and
precedents (תקדימים). Supported formats: PDF (with a text layer), DOCX, TXT, MD.

Uploads are parsed, split into section-aware chunks, embedded locally with
`intfloat/multilingual-e5-base` (768 dimensions, downloaded from Hugging Face
on first use), and stored in pgvector. During chat, Claude calls the
`search_legal_database` tool, which embeds the query and returns the top
matching chunks with their source document names for citation. The tool
supports narrowing by category and document type.

### Categories and auto-classification

Documents are organized by category (editable labor-law taxonomy, seeded on
first run). When uploading with type/category set to "אוטומטי", Claude
classifies the document: court decisions are stored as precedents with
extracted metadata (case number, court, parties, decision date) used for
formal citations. Type and category can be edited inline in the מאגר ידע tab.

### Court-decision research

Chat can search the public web for Israeli case law (Anthropic server-side
web search + fetch; $10 per 1,000 searches). Found decisions are quoted with
full citations and source URLs, and can be saved into the knowledge base as
precedents via the `save_precedent` tool. Subscriber-only databases (Nevo,
Takdin) are not accessible — download from them manually and upload here.

## Chat features

- **Streaming** - responses stream token-by-token over SSE (`POST /api/chat`).
- **Conversations** - chat history is stored server-side in Postgres; the
  sidebar lists past conversations (create/open/delete).
- **Task templates** - one-click presets for recurring lawyer tasks: pleading
  draft (כתב טענות), evidentiary analysis (ניתוח מסמך ראייתי), cross-examination
  prep (חקירה נגדית), and summations (סיכומים). Selecting a template pre-retrieves
  matching guidelines/examples from the knowledge base into the prompt.

### 2. Frontend (React + Vite)

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 in a browser.

Environment variables (set in `frontend/.env.local` if needed):

- `VITE_API_URL` - Backend base URL. Defaults to `http://127.0.0.1:8000`.
