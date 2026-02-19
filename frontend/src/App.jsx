import { useState } from "react";
import UploadForm from "./components/UploadForm";
import DocumentsList from "./components/DocumentsList";
import OcrResult from "./components/OcrResult";
import { uploadDocument } from "./services/api";
import ReviewPage from "./review/ReviewPage";
import { navigateTo, useAppRoute } from "./review/routing";

export default function App() {
  const route = useAppRoute();
  const reviewEnabled = import.meta.env.VITE_REVIEW_FEATURE_ENABLED !== "0";
  const [uploadResult, setUploadResult] = useState(null);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const handleUpload = async (file) => {
    // Upload -> show latest result -> refresh documents list.
    setUploadLoading(true);
    setUploadError("");
    setUploadResult(null);

    try {
      const data = await uploadDocument(file);
      setUploadResult(data);
      setRefreshKey((prev) => prev + 1);
    } catch (err) {
      setUploadError(err?.response?.data?.detail || err.message || "Upload failed");
    } finally {
      setUploadLoading(false);
    }
  };

  if (route.type === "review") {
    if (!reviewEnabled) {
      return (
        <div className="app">
          <section className="panel">
            <p className="state error">Review feature is disabled.</p>
            <button type="button" className="btn primary" onClick={() => navigateTo("/")}>
              Retour a la liste
            </button>
          </section>
        </div>
      );
    }

    return (
      <div className="app">
        <ReviewPage documentId={route.documentId} onBack={() => navigateTo("/")} />
      </div>
    );
  }

  return (
    <div className="app">
      <header className="hero">
        <div className="hero-content">
          <span className="badge">GLM-OCR</span>
          <h1>Scan, extract, and structure your documents.</h1>
          <p>
            Upload PDFs or images, get structured JSON instantly, and keep a
            searchable archive.
          </p>
        </div>
      </header>

      <main className="grid">
        <UploadForm onUpload={handleUpload} loading={uploadLoading} error={uploadError} />

        <OcrResult text={uploadResult?.raw_text || ""} loading={uploadLoading} />

        <DocumentsList
          refreshKey={refreshKey}
          onOpenReview={
            reviewEnabled
              ? (documentId) => navigateTo(`/documents/${documentId}/review`)
              : null
          }
        />
      </main>
    </div>
  );
}
