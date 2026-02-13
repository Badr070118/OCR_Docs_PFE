import { useEffect, useState } from "react";
import { fetchDocuments, processWithLlama, saveDocumentData } from "../services/api";

export default function DocumentsList({ refreshKey }) {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [activeView, setActiveView] = useState("ocr");
  const [instruction, setInstruction] = useState(
    "Structure le texte OCR en JSON clair pour la base."
  );
  const [llamaLoading, setLlamaLoading] = useState(false);
  const [llamaError, setLlamaError] = useState("");
  const [pendingStructuredById, setPendingStructuredById] = useState({});
  const [saveLoading, setSaveLoading] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveInfo, setSaveInfo] = useState("");

  useEffect(() => {
    let isMounted = true;
    setLoading(true);
    setError("");

    fetchDocuments()
      .then((data) => {
        if (isMounted) {
          const items = Array.isArray(data) ? data : [];
          setDocuments(items);
          setSelectedId((current) => {
            if (current && items.some((doc) => doc.id === current)) {
              return current;
            }
            return items.length > 0 ? items[0].id : null;
          });
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err?.response?.data?.detail || err.message || "Failed to load");
        }
      })
      .finally(() => {
        if (isMounted) {
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [refreshKey]);

  const selectedDoc = documents.find((doc) => doc.id === selectedId) || null;
  const pendingStructured = selectedId ? pendingStructuredById[selectedId] : null;

  useEffect(() => {
    setSaveError("");
    setSaveInfo("");
  }, [selectedId]);

  const handleAskLlama = async () => {
    if (!selectedDoc || !selectedDoc.raw_text || llamaLoading) {
      return;
    }

    setLlamaLoading(true);
    setLlamaError("");
    setSaveError("");
    setSaveInfo("");

    try {
      const payload = await processWithLlama({
        text: selectedDoc.raw_text,
        instruction: instruction.trim() || null,
        documentId: selectedDoc.id,
        syncData: false,
      });

      setDocuments((prev) =>
        prev.map((doc) =>
          doc.id === selectedDoc.id
            ? {
                ...doc,
                llama_output: payload.generated_text || "",
              }
            : doc
        )
      );

      if (payload.structured_data) {
        setPendingStructuredById((prev) => ({
          ...prev,
          [selectedDoc.id]: payload.structured_data,
        }));
        setActiveView("json");
      } else {
        setActiveView("llama");
      }
    } catch (err) {
      setLlamaError(
        err?.response?.data?.detail || err.message || "Failed to contact Llama"
      );
    } finally {
      setLlamaLoading(false);
    }
  };

  const handleSaveStructured = async () => {
    if (!selectedDoc || !pendingStructured || saveLoading) {
      return;
    }

    setSaveLoading(true);
    setSaveError("");
    setSaveInfo("");

    try {
      const updated = await saveDocumentData({
        documentId: selectedDoc.id,
        data: pendingStructured,
        merge: true,
      });

      setDocuments((prev) =>
        prev.map((doc) => (doc.id === selectedDoc.id ? updated : doc))
      );

      setPendingStructuredById((prev) => {
        const next = { ...prev };
        delete next[selectedDoc.id];
        return next;
      });
      setSaveInfo("JSON structure enregistre en base.");
      setActiveView("json");
    } catch (err) {
      setSaveError(err?.response?.data?.detail || err.message || "Save failed");
    } finally {
      setSaveLoading(false);
    }
  };

  const renderContent = () => {
    if (!selectedDoc) {
      return <p className="state">Select a document to read its content.</p>;
    }

    if (activeView === "ocr") {
      return (
        <pre className="doc-content">
          {selectedDoc.raw_text || "No OCR text stored for this document."}
        </pre>
      );
    }

    if (activeView === "llama") {
      return (
        <pre className="doc-content">
          {selectedDoc.llama_output || "No Llama output yet for this document."}
        </pre>
      );
    }

    const jsonPayload = pendingStructured || selectedDoc.data || {};
    return (
      <>
        {pendingStructured && (
          <p className="state">Apercu JSON non sauvegarde. Clique "Sauvegarder JSON en base".</p>
        )}
        <pre className="doc-content">{JSON.stringify(jsonPayload, null, 2)}</pre>
      </>
    );
  };

  return (
    <section className="panel table-panel">
      <div className="panel-header">
        <h2>Documents Reader</h2>
        <p>Browse saved files and read OCR or Llama content.</p>
      </div>

      {loading && <p className="state">Loading documents...</p>}
      {error && <p className="state error">Error: {error}</p>}

      {!loading && !error && (
        <div className="docs-reader">
          <aside className="docs-sidebar">
            {documents.length === 0 && <p className="empty">No documents yet.</p>}
            {documents.map((doc) => (
              <button
                key={doc.id}
                type="button"
                className={`doc-item ${selectedId === doc.id ? "active" : ""}`}
                onClick={() => setSelectedId(doc.id)}
              >
                <strong>
                  #{doc.id} {doc.file_name}
                </strong>
                <span>{new Date(doc.date_uploaded).toLocaleString()}</span>
              </button>
            ))}
          </aside>

          <section className="docs-detail">
            <div className="doc-meta">
              <h3>
                {selectedDoc
                  ? `#${selectedDoc.id} - ${selectedDoc.file_name}`
                  : "No selection"}
              </h3>
              {selectedDoc && (
                <p>Uploaded: {new Date(selectedDoc.date_uploaded).toLocaleString()}</p>
              )}
            </div>

            <div className="llama-ask">
              <label className="field">
                <span>Instruction Llama (structuration)</span>
                <input
                  className="input"
                  type="text"
                  value={instruction}
                  onChange={(event) => setInstruction(event.target.value)}
                  placeholder="Ex: Structure en JSON pour la base, sans texte additionnel."
                />
              </label>
              <button
                type="button"
                className="btn primary"
                onClick={handleAskLlama}
                disabled={!selectedDoc?.raw_text || llamaLoading}
              >
                {llamaLoading ? "Structuration..." : "Structurer avec Llama"}
              </button>
              <button
                type="button"
                className="btn primary"
                onClick={handleSaveStructured}
                disabled={!pendingStructured || saveLoading}
              >
                {saveLoading ? "Sauvegarde..." : "Sauvegarder JSON en base"}
              </button>
              {llamaError && <p className="state error">Error: {llamaError}</p>}
              {saveError && <p className="state error">Error: {saveError}</p>}
              {saveInfo && <p className="state">{saveInfo}</p>}
              {!selectedDoc?.raw_text && (
                <p className="state">Ce document ne contient pas de texte OCR exploitable.</p>
              )}
            </div>

            <div className="doc-tabs">
              <button
                type="button"
                className={`tab ${activeView === "ocr" ? "active" : ""}`}
                onClick={() => setActiveView("ocr")}
              >
                OCR text
              </button>
              <button
                type="button"
                className={`tab ${activeView === "llama" ? "active" : ""}`}
                onClick={() => setActiveView("llama")}
              >
                Llama output
              </button>
              <button
                type="button"
                className={`tab ${activeView === "json" ? "active" : ""}`}
                onClick={() => setActiveView("json")}
              >
                Extracted JSON
              </button>
            </div>

            {renderContent()}
          </section>
        </div>
      )}
    </section>
  );
}
