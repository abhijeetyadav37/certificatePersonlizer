# PromptEdit — First Version

PromptEdit is an early prototype for editing text in images and PDF documents using simple text instructions.

The first version explores a basic workflow:

1. Upload an image or PDF.
2. Detect text using OCR where needed.
3. enter an instruction such as `Replace "OLD TEXT" with "NEW TEXT"`.
4. Attempt to remove the original text and draw the replacement.
5. Preview and export the result.

> **Prototype note:** This is an early version, not a pixel-perfect document reconstruction tool. Font matching, spacing, alignment, and background restoration can be imperfect. Always review the output before using it.

## Example

The following illustration is a **mock example** of the intended workflow. It is not a screenshot of a real processing result.

![Illustrative before and after example](assets/before-after.svg)

Open [`example.html`](example.html) in a browser to see a standalone example page with the same illustrative before/after workflow.

## Main technologies

- **React + Vite** — web interface
- **Python + FastAPI** — backend API
- **Tesseract OCR** — text recognition in images/scanned pages
- **OpenCV** — basic image cleanup/inpainting
- **Pillow** — image drawing and rendering
- **PyMuPDF** — PDF reading, rendering, and PDF-related operations
- **Optional AI integration** — may be configured for more flexible prompt interpretation; availability depends on the version and configuration

## How it works

```text
Upload image/PDF
      |
      v
Read PDF text or run OCR
      |
      v
Interpret the editing instruction
      |
      v
Remove/cover the original text where possible
      |
      v
Draw replacement text and generate preview
      |
      v
Export image/PDF
```

## Example prompts

- `Replace "WELCOME" with "HELLO"`
- `Change "Summer Sale" to "Winter Sale"`
- `Replace "Monday" with "Friday"`

The exact commands supported depend on the prompt parser implemented in the version you run.

## Windows setup

### Requirements

- Windows 10 or Windows 11
- Python 3.11 recommended
- Node.js and npm
- Tesseract OCR installed if the backend uses OCR
- Git (optional)

### 1. Start the backend

Open PowerShell in the backend folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```

If your project uses a different backend entry point or requirements file, follow the paths in your repository.

### 2. Start the frontend

Open a second PowerShell window in the frontend folder:

```powershell
npm install
npm run dev
```

Open the local URL printed by Vite, commonly `http://localhost:5173`.

### 3. Check the backend

If your backend exposes a health route, open its documented URL (for example, `http://127.0.0.1:8000/health`). The exact route depends on the source code in your version.

## Configuration

Keep secrets such as AI provider API keys in backend environment variables. Do not place secret keys in React/Vite frontend code or commit them to Git.

If no AI provider is configured, the app may only understand the limited set of prompt patterns implemented locally.

## Current limitations

- OCR can misread text, especially small, low-contrast, rotated, or decorative text.
- The replacement font may not match the original font exactly.
- OpenCV inpainting can leave visible artifacts on patterned or complex backgrounds.
- Scanned PDFs behave more like images; text is not necessarily selectable.
- A successful API response does not guarantee a visually perfect result.
- Review the preview and keep the original file unchanged.

## Suggested first-version roadmap

- Improve OCR region selection.
- Preserve text size, color, alignment, and line spacing more reliably.
- Add undo/reset and before/after comparison.
- Add clearer errors when a prompt is unsupported.
- Add tests for PDF, scanned PDF, PNG, and JPEG inputs.

## Project status

This README describes the **first prototype concept**. Update the commands, API routes, screenshots, and feature list to match the exact source files in your local repository before publishing it.
