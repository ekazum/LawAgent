# LawAgent

Desktop-ready legal assistant for Israeli employment law.

## Project structure

- `/home/runner/work/LawAgent/LawAgent/backend/main.py` - FastAPI backend with Gemini + legal tool function.
- `/home/runner/work/LawAgent/LawAgent/backend/requirements.txt` - Backend dependencies.
- `/home/runner/work/LawAgent/LawAgent/frontend` - React + TypeScript UI (Vite).
- `/home/runner/work/LawAgent/LawAgent/src-tauri` - Tauri host app and Python sidecar configuration.
- `/home/runner/work/LawAgent/LawAgent/app.py` - Original Streamlit implementation (kept for reference).

## Backend (FastAPI)

```bash
cd /home/runner/work/LawAgent/LawAgent/backend
pip install -r requirements.txt
GEMINI_API_KEY=your_key uvicorn main:app --host 127.0.0.1 --port 8000
```

## Frontend (React)

```bash
cd /home/runner/work/LawAgent/LawAgent/frontend
npm install
npm run dev
```

## Tauri desktop

1. Ensure the backend sidecar binary exists at:
   - `/home/runner/work/LawAgent/LawAgent/src-tauri/bin/python-backend` (Linux/macOS), or
   - `/home/runner/work/LawAgent/LawAgent/src-tauri/bin/python-backend.exe` (Windows).
2. Install frontend dependencies:

```bash
cd /home/runner/work/LawAgent/LawAgent/frontend
npm install
```

3. Run Tauri (from project root, if Tauri CLI is installed):

```bash
cd /home/runner/work/LawAgent/LawAgent
npx tauri dev --config /home/runner/work/LawAgent/LawAgent/src-tauri/tauri.conf.json
```

## Build Python sidecar with PyInstaller

```bash
cd /home/runner/work/LawAgent/LawAgent/backend
pip install pyinstaller -r requirements.txt
pyinstaller --onefile --name python-backend main.py
cp dist/python-backend /home/runner/work/LawAgent/LawAgent/src-tauri/bin/python-backend
```

On Windows, copy `dist/python-backend.exe` instead.
