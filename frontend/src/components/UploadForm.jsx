import { useState } from "react";

export default function UploadForm({ onUpload, loading, error }) {
  const [file, setFile] = useState(null);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!file || loading) {
      return;
    }
    await onUpload(file);
  };

  return (
    <form className="panel upload-panel" onSubmit={handleSubmit}>
      <div className="panel-header">
        <h2>Upload OCR Document</h2>
        <p>PDF or image (jpg, jpeg, png).</p>
      </div>

      <label className="file-input">
        <input
          type="file"
          accept=".pdf,.jpg,.jpeg,.png"
          onChange={(event) => setFile(event.target.files?.[0] || null)}
        />
        <span>{file ? file.name : "Choose a file"}</span>
      </label>

      <button className="btn primary" type="submit" disabled={!file || loading}>
        {loading ? "Uploading..." : "Upload"}
      </button>

      {error && <p className="state error">Error: {error}</p>}
    </form>
  );
}
