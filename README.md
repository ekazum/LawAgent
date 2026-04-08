# LawAgent

Desktop-ready legal assistant for Israeli employment law.

## Project structure

- `backend/main.py` - FastAPI backend with Gemini + legal tool function.
- `backend/requirements.txt` - Backend dependencies.
- `frontend/` - React + TypeScript UI (Vite).
- `src-tauri/` - Tauri host app and Python sidecar configuration.
- `app.py` - Original Streamlit implementation (kept for reference).

## Backend (FastAPI)

```bash
cd backend
pip install -r requirements.txt
GEMINI_API_KEY=your_key uvicorn main:app --host 127.0.0.1 --port 8000
```

## Frontend (React)

```bash
cd frontend
npm install
npm run dev
```

## Tauri desktop

1. Ensure the backend sidecar binary exists at:
   - `src-tauri/bin/python-backend` (Linux/macOS), or
   - `src-tauri/bin/python-backend.exe` (Windows).
2. Install frontend dependencies:

```bash
cd frontend
npm install
```

3. Run Tauri (from project root, if Tauri CLI is installed):

```bash
npx tauri dev --config src-tauri/tauri.conf.json
```

## Build Python sidecar with PyInstaller

```bash
cd backend
pip install pyinstaller -r requirements.txt
pyinstaller --onefile --name python-backend main.py
cp dist/python-backend ../src-tauri/bin/python-backend
```

On Windows, copy `dist/python-backend.exe` instead.
