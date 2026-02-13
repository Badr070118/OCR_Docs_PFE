import { useState } from "react";
import { processWithLlama } from "../services/api";

export default function LlamaResult({ text, documentId }) {
  const [instruction, setInstruction] = useState(
    "Donne uniquement le numero de facture, le nom du responsable et le montant."
  );
  const [result, setResult] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleGenerate = async () => {
    if (!text || loading) {
      return;
    }

    setLoading(true);
    setError("");
    setResult("");

    try {
      const payload = await processWithLlama({
        text,
        instruction: instruction.trim() || null,
        documentId,
      });
      setResult(payload.generated_text || "");
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Failed to generate");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="panel ai-panel">
      <div className="panel-header">
        <h2>LLaMA Result</h2>
        <p>Post-process the OCR text with a local LLaMA model.</p>
      </div>

      <label className="field">
        <span>Prompt</span>
        <input
          className="input"
          type="text"
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder="Ex: Donne uniquement le numero de facture et le montant."
        />
      </label>

      <button className="btn primary" onClick={handleGenerate} disabled={!text || loading}>
        {loading ? "Generating..." : "Generer avec IA"}
      </button>

      {error && <p className="state error">Error: {error}</p>}
      {result && <pre className="result">{result}</pre>}
      {!result && !loading && text && (
        <p className="state">Click "Generer avec IA" to analyze the OCR text.</p>
      )}
      {!text && <p className="state">Upload a file to enable LLaMA processing.</p>}
    </section>
  );
}
