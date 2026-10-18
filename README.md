# Smart Certificate Field Detector and Template Personalizer

An educational web application for extracting text from documents,
detecting candidate fields, and personalizing original or authorized
certificate templates.

## Technology stack

- React and Vite
- JavaScript and CSS
- Python and FastAPI
- PyMuPDF and Tesseract OCR (planned)
- PDF export (planned)

## Current status

Phase 1: Frontend and backend setup.

## Run the frontend

cd frontend
npm install
npm run dev

## Run the backend

cd backend
python -m venv .venv

# Activate the virtual environment in Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000

## Backend endpoints

- GET /health
- GET /docs

## Privacy and responsible use

Documents are intended for local processing.
Use only documents you own or are authorized to modify.
Generated samples must not misrepresent an issuer or credential.