import { useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export default function OcrAiGenerator() {
  const [inputText, setInputText] = useState("");
  const [instruction, setInstruction] = useState(
    "Donne uniquement le nom du responsable et le montant."
  );
  const [resultText, setResultText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleGenerate = async () => {
    if (!inputText.trim() || loading) {
      return;
    }

    setLoading(true);
    setError("");
    setResultText("");

    try {
      const trimmedInstruction = instruction.trim();
      const response = await fetch(`${API_BASE_URL}/generate_with_llama`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: inputText,
          instruction: trimmedInstruction ? trimmedInstruction : null,
        }),
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Generation failed");
      }

      const data = await response.json();
      setResultText(data.result || "");
    } catch (err) {
      setError(err.message || "Failed to generate");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="panel ai-panel">
      <div className="panel-header">
        <h2>OCR AI Generator</h2>
        <p>Paste OCR text and generate a response with LLaMA.</p>
      </div>

      <textarea
        className="textarea"
        rows="6"
        placeholder="Paste OCR text here..."
        value={inputText}
        onChange={(event) => setInputText(event.target.value)}
      />

      <label className="field">
        <span>Prompt</span>
        <input
          className="input"
          type="text"
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder="Ex: Donne uniquement le nom du responsable et le montant."
        />
      </label>

      <button className="btn primary" onClick={handleGenerate} disabled={loading}>
        {loading ? "Generating..." : "Generer avec IA"}
      </button>

      {error && <p className="state error">Error: {error}</p>}
      {resultText && <pre className="result">{resultText}</pre>}
    </section>
  );
}
