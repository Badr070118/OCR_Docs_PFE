export default function OcrResult({ text, loading }) {
  return (
    <section className="panel result-panel">
      <div className="panel-header">
        <h2>OCR Text</h2>
        <p>Raw text extracted from the uploaded file.</p>
      </div>

      {loading && <p className="state">Extracting text...</p>}
      {!loading && !text && (
        <p className="state">Upload a file to see the OCR text.</p>
      )}
      {!loading && text && <pre className="result">{text}</pre>}
    </section>
  );
}
