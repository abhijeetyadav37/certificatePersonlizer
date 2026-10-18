import { useEffect, useRef, useState } from "react";
import "./App.css";

const API_URL = "http://127.0.0.1:8000";
const MAX_FILE_SIZE = 10 * 1024 * 1024;
const ACCEPTED_TYPES = {
  ".pdf": "application/pdf",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
};

function getExtension(filename = "") {
  return filename.slice(filename.lastIndexOf(".")).toLowerCase();
}

function validateFile(file) {
  if (!file) return "Please select a file.";
  const extension = getExtension(file.name);
  if (!ACCEPTED_TYPES[extension]) return "Only single-page PDF, PNG, JPG, and JPEG files are supported.";
  if (file.type !== ACCEPTED_TYPES[extension]) return "The file extension and file type do not match.";
  if (!file.size) return "The selected file is empty.";
  if (file.size > MAX_FILE_SIZE) return "The maximum file size is 10 MB.";
  return "";
}

async function readApiError(response, fallback) {
  try {
    const data = await response.json();
    return data.detail || fallback;
  } catch {
    return fallback;
  }
}

function App() {
  const fileInputRef = useRef(null);
  const [backendStatus, setBackendStatus] = useState("checking");
  const [engine, setEngine] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [result, setResult] = useState(null);
  const [editedLines, setEditedLines] = useState({});
  const [processing, setProcessing] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [generationError, setGenerationError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewFilename, setPreviewFilename] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function checkBackend() {
      try {
        const response = await fetch(`${API_URL}/health`);
        if (!response.ok) throw new Error("Backend health check failed");
        const data = await response.json();
        const engineResponse = await fetch(`${API_URL}/api/engine`);
        const engineData = engineResponse.ok ? await engineResponse.json() : null;
        if (!cancelled) {
          setBackendStatus(data.status === "ok" ? "online" : "offline");
          setEngine(engineData);
        }
      } catch {
        if (!cancelled) setBackendStatus("offline");
      }
    }
    checkBackend();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  function clearPreview() {
    setPreviewUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return "";
    });
    setPreviewFilename("");
    setGenerationError("");
  }

  async function processFile(file) {
    const validationError = validateFile(file);
    setError(validationError);
    if (validationError) return;
    if (backendStatus !== "online") {
      setError("Backend is offline. Start the FastAPI server and try again.");
      return;
    }

    setSelectedFile(file);
    setResult(null);
    setEditedLines({});
    clearPreview();
    setProcessing(true);
    setError("");

    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch(`${API_URL}/api/extract`, { method: "POST", body: formData });
      if (!response.ok) throw new Error(await readApiError(response, "Could not process the document."));
      const data = await response.json();
      setResult(data);
      setEditedLines(Object.fromEntries((data.lines || []).map((line) => [line.id, line.text])));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong while processing the document.");
    } finally {
      setProcessing(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function handleFileChange(event) {
    const file = event.target.files?.[0];
    if (file) processFile(file);
  }

  function handleDrop(event) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) processFile(file);
    else setError("Please drop a file into the upload area.");
  }

  function updateLine(lineId, value) {
    setEditedLines((current) => ({ ...current, [lineId]: value }));
    clearPreview();
  }

  async function generateDocument(format, download = false) {
    if (!selectedFile || !result?.lines?.length) return;
    const edits = result.lines.map((line) => ({
      id: line.id,
      original_text: line.text,
      text: editedLines[line.id] ?? line.text,
      bbox: line.bbox,
    }));
    if (!edits.some((edit) => edit.text !== edit.original_text)) {
      setGenerationError("Edit at least one extracted text line before generating a preview.");
      return;
    }

    setGenerating(true);
    setGenerationError("");
    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      formData.append("edits_json", JSON.stringify(edits));
      formData.append("output_format", format);
      const response = await fetch(`${API_URL}/api/generate`, { method: "POST", body: formData });
      if (!response.ok) throw new Error(await readApiError(response, "Document generation failed."));
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const filename = format === "pdf" ? "personalized-preview.pdf" : "personalized-preview.png";
      if (download) {
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      } else {
        setPreviewUrl((current) => {
          if (current) URL.revokeObjectURL(current);
          return url;
        });
        setPreviewFilename(filename);
      }
    } catch (err) {
      setGenerationError(err instanceof Error ? err.message : "Unable to generate this document.");
    } finally {
      setGenerating(false);
    }
  }

  function resetDocument() {
    setSelectedFile(null);
    setResult(null);
    setEditedLines({});
    setError("");
    setGenerationError("");
    clearPreview();
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  const changedCount = result?.lines?.filter((line) => (editedLines[line.id] ?? line.text) !== line.text).length || 0;

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Certificate Studio home"><span className="brand-icon">C</span><span>Certificate Studio</span></a>
        <div className="status"><span className={`status-dot ${backendStatus}`} aria-hidden="true" /><span>Backend: {backendStatus === "checking" ? "Checking..." : backendStatus === "online" ? "Connected" : "Offline"}</span></div>
      </header>

      <section className="hero">
        <span className="eyebrow">DOCUMENT WORKSPACE · COORDINATE-BASED EDITING</span>
        <h1>Edit extracted text.<br /><span>Keep the original document as the background.</span></h1>
        <p className="hero-description">Upload one PDF or image, edit the recognized lines directly, then generate a watermarked preview using their detected positions. No second template upload and no exact-text searching.</p>
      </section>

      <section className="workspace" aria-labelledby="upload-heading">
        <div className="section-heading"><div><span className="step-label">STEP 01</span><h2 id="upload-heading">Upload your document</h2></div><span className="file-types">PDF · PNG · JPG · JPEG</span></div>
        <div className={`upload-card ${dragging ? "dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={handleDrop}>
          <div className="upload-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V4" /><path d="m7 9 5-5 5 5" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></svg></div>
          <h3>Upload a document you own or are authorized to edit</h3>
          <p>Drag and drop a single-page PDF or image here, or choose it from your device. Files up to 10 MB are processed locally.</p>
          <input ref={fileInputRef} id="document-upload" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" hidden onChange={handleFileChange} disabled={processing} />
          <button className="primary-button" type="button" disabled={processing || backendStatus !== "online"} onClick={() => fileInputRef.current?.click()}>{processing ? "Extracting text..." : "Choose file"}</button>
          {selectedFile && <span className="selected-file">{selectedFile.name} · {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB</span>}
          <span className="privacy-note"><span aria-hidden="true">●</span> Temporary local processing · No permanent document storage</span>
        </div>
        {engine && <div className="engine-status"><strong>Text engine:</strong> {engine.ocr_engine} <span>·</span> <strong>Background cleanup:</strong> {engine.background_cleanup}</div>}
        {processing && <div className="feedback processing-message" role="status"><span className="spinner" /> Reading text and locating each line...</div>}
        {error && <div className="feedback error-message" role="alert"><strong>Unable to process file</strong><p>{error}</p><button type="button" className="text-button" onClick={resetDocument}>Try another file</button></div>}

        {result && <section className="extracted-panel" aria-labelledby="result-heading">
          <div className="result-header"><div><span className="step-label">STEP 02</span><h2 id="result-heading">Edit extracted text</h2></div><button type="button" className="text-button" onClick={resetDocument}>Upload another</button></div>
          <div className="result-meta"><span>{result.method === "easyocr_ai" ? "Local AI OCR" : result.method === "pdf_text_layer" ? "PDF text layer" : "OCR extraction"}</span><span>{result.lines?.length || 0} text lines</span>{result.confidence != null && <span>Average confidence: {result.confidence}%</span>}</div>
          <p className="result-disclaimer">Edit any line below. Each edit stays linked to the coordinates where that line was detected, so generation does not search for a matching string. Check OCR mistakes before previewing.</p>
          {result.lines?.length ? <div className="editable-lines">{result.lines.map((line, index) => <article className="editable-line" key={line.id}>
            <div className="line-number">{String(index + 1).padStart(2, "0")}</div>
            <div className="line-editor"><label htmlFor={`line-${line.id}`}>Extracted line {index + 1}</label><textarea id={`line-${line.id}`} rows={Math.max(1, Math.min(3, Math.ceil((editedLines[line.id] ?? line.text).length / 75)))} value={editedLines[line.id] ?? line.text} onChange={(event) => updateLine(line.id, event.target.value)} /></div>
            <div className="line-coordinates">x {line.bbox.x} · y {line.bbox.y}<br />{line.bbox.width} × {line.bbox.height}px</div>
            {(editedLines[line.id] ?? line.text) !== line.text && <span className="edited-tag">Edited</span>}
          </article>)}</div> : <p className="empty-result">No text was detected. Try a clearer scan or image.</p>}

          <div className="generation-panel" aria-labelledby="generation-heading">
            <span className="step-label">STEP 03</span><h2 id="generation-heading">Preview your edits</h2>
            <p>{changedCount} line{changedCount === 1 ? "" : "s"} changed. The app will clear the old text area using local image cleanup, then draw your edited text at the detected coordinates. Complex backgrounds may need manual cleanup.</p>
            <div className="generation-actions"><button className="primary-button" type="button" disabled={generating || changedCount === 0} onClick={() => generateDocument("png")}>{generating ? "Generating..." : "Generate preview"}</button><button className="secondary-button" type="button" disabled={generating || changedCount === 0} onClick={() => generateDocument("png", true)}>Download PNG</button><button className="secondary-button" type="button" disabled={generating || changedCount === 0} onClick={() => generateDocument("pdf", true)}>Download PDF</button></div>
            {generationError && <div className="feedback error-message" role="alert">{generationError}</div>}
            {previewUrl && <div className="generated-preview"><div className="result-header"><h3>Generated preview</h3><span className="page-info">{previewFilename}</span></div><img src={previewUrl} alt="Watermarked personalized document preview" /></div>}
            <p className="preview-disclaimer">For authorized documents and design mockups only. Every generated output includes a visible watermark and must not be represented as an official credential.</p>
          </div>
        </section>}
      </section>

      <section className="workflow" aria-label="Application workflow"><div className="section-heading"><div><span className="step-label">NEW WORKFLOW</span><h2>Text-first editing</h2></div></div><div className="workflow-grid"><article className="workflow-card"><span className="workflow-number">01</span><h3>Detect coordinates</h3><p>OCR returns each line's text and bounding box.</p><span className="coming-soon">AVAILABLE</span></article><article className="workflow-card"><span className="workflow-number">02</span><h3>Edit the lines</h3><p>Correct or replace extracted text without a field-detection step.</p><span className="coming-soon">AVAILABLE</span></article><article className="workflow-card"><span className="workflow-number">03</span><h3>Restore & preview</h3><p>Clean old text regions, place replacements, and export a watermarked preview.</p><span className="coming-soon">BETA</span></article></div></section>
      <footer className="footer"><span>Certificate Studio</span><span>Educational project · Authorized documents only</span></footer>
    </main>
  );
}

export default App;
