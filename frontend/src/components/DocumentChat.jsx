import { useMemo, useState } from "react";
import { askDocumentQuestion } from "../services/api";

const QUICK_QUESTIONS = [
  "Quel est le montant total ?",
  "Quel est le montant de la TVA ?",
  "Quelle est la date du document ?",
  "Quel est le fournisseur/émetteur ?",
  "Liste les articles/ligne(s) avec quantité et prix",
];

function makeMessage(role, content) {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    role,
    content,
  };
}

export default function DocumentChat({ docId, structuredJson, ocrText }) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [messagesByDoc, setMessagesByDoc] = useState({});

  const messages = useMemo(() => messagesByDoc[docId] || [], [messagesByDoc, docId]);
  const structuredFieldsCount = useMemo(
    () =>
      structuredJson && typeof structuredJson === "object"
        ? Object.keys(structuredJson).length
        : 0,
    [structuredJson]
  );

  const appendMessage = (message) => {
    setMessagesByDoc((prev) => ({
      ...prev,
      [docId]: [...(prev[docId] || []), message],
    }));
  };

  const handleAsk = async (forcedQuestion) => {
    if (!docId || loading) {
      return;
    }

    const finalQuestion = (forcedQuestion ?? question).trim();
    if (!finalQuestion) {
      return;
    }

    setError("");
    setLoading(true);
    appendMessage(makeMessage("user", finalQuestion));
    setQuestion("");

    try {
      const payload = await askDocumentQuestion({
        documentId: docId,
        question: finalQuestion,
      });
      appendMessage(makeMessage("assistant", payload));
    } catch (err) {
      const detail =
        err?.response?.data?.detail || err.message || "Question processing failed";
      setError(detail);
      appendMessage(
        makeMessage("assistant", {
          answer: "Non trouvé dans ce document",
          found: false,
          fields_used: [],
          evidence: [],
          confidence: 0,
        })
      );
    } finally {
      setLoading(false);
    }
  };

  const renderAssistantContent = (payload) => {
    const evidence = Array.isArray(payload?.evidence) ? payload.evidence : [];
    const fieldsUsed = Array.isArray(payload?.fields_used) ? payload.fields_used : [];
    const confidence = Number(payload?.confidence || 0);
    const confidencePct = Math.round(Math.max(0, Math.min(1, confidence)) * 100);

    return (
      <div className="chat-assistant">
        <p className="chat-answer">{payload?.answer || "Non trouvé dans ce document"}</p>
        <div className="chat-badges">
          <span className={`found-badge ${payload?.found ? "yes" : "no"}`}>
            {payload?.found ? "Found" : "Not found"}
          </span>
          <span className="confidence-badge">Confidence: {confidencePct}%</span>
        </div>

        <div className="chat-proof">
          <strong>Source / Preuves</strong>
          {fieldsUsed.length > 0 && (
            <div className="proof-block">
              <span>Champs JSON:</span>
              <ul>
                {fieldsUsed.map((field) => (
                  <li key={field}>
                    <code>{field}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {evidence.length > 0 && (
            <div className="proof-block">
              <span>Extraits OCR:</span>
              <ul>
                {evidence.map((item, index) => (
                  <li key={`${index}-${item.slice(0, 24)}`}>
                    <code>{item}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {fieldsUsed.length === 0 && evidence.length === 0 && (
            <p className="state">Aucune preuve exploitable fournie.</p>
          )}
        </div>
      </div>
    );
  };

  return (
    <section className="doc-chat">
      <p className="state chat-context">
        Context: {structuredFieldsCount} champ(s) JSON structuré, {ocrText?.length || 0}{" "}
        caractères OCR.
      </p>

      <div className="chat-quick">
        {QUICK_QUESTIONS.map((item) => (
          <button
            key={item}
            type="button"
            className="tab"
            disabled={loading}
            onClick={() => handleAsk(item)}
          >
            {item}
          </button>
        ))}
      </div>

      <div className="chat-input-row">
        <input
          className="input"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Pose une question sur ce document..."
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              handleAsk();
            }
          }}
        />
        <button type="button" className="btn primary" onClick={() => handleAsk()} disabled={loading}>
          {loading ? "Analyse..." : "Envoyer"}
        </button>
      </div>

      {error && <p className="state error">Error: {error}</p>}

      <div className="chat-history">
        {messages.length === 0 && (
          <p className="state">Pose une question pour demarrer le chat sur ce document.</p>
        )}

        {messages.map((message) => (
          <article key={message.id} className={`chat-message ${message.role}`}>
            {message.role === "user" ? (
              <p>{message.content}</p>
            ) : (
              renderAssistantContent(message.content)
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
