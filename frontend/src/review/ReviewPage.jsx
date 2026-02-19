import { useEffect, useMemo, useRef, useState } from "react";
import {
  buildReviewPreviewUrl,
  fetchReviewDocument,
  fetchReviewPreviewMeta,
  saveReviewDocument,
} from "../services/reviewApi";
import {
  bboxToRect,
  clamp,
  computeZoomToFit,
  normalizeBBox,
  rectCenter,
} from "./highlightUtils";
import "./review.css";

const ENHANCED_HIGHLIGHTS_ENABLED =
  (import.meta.env.VITE_ENHANCED_HIGHLIGHTS ??
    import.meta.env.VITE_REVIEW_ENHANCED_HIGHLIGHTS ??
    "1") !== "0";
const AUTO_ZOOM_DEFAULT =
  (import.meta.env.VITE_REVIEW_AUTO_ZOOM_DEFAULT ?? "0") !== "0";

const PRIORITY_FIELDS = [
  "supplier_name",
  "fournisseur",
  "date",
  "city",
  "ville",
  "country",
  "pays",
  "montant",
  "total",
  "tva",
  "ice",
  "rib",
  "iban",
  "numero_facture",
  "adresse",
  "email",
];

function readValue(payloadValue) {
  if (payloadValue === null || payloadValue === undefined) {
    return "";
  }
  if (typeof payloadValue === "string" || typeof payloadValue === "number") {
    return String(payloadValue);
  }
  if (typeof payloadValue === "object") {
    if ("value" in payloadValue) {
      return payloadValue.value === null || payloadValue.value === undefined
        ? ""
        : String(payloadValue.value);
    }
    if ("text" in payloadValue) {
      return payloadValue.text === null || payloadValue.text === undefined
        ? ""
        : String(payloadValue.text);
    }
  }
  return JSON.stringify(payloadValue);
}

function asList(value) {
  if (Array.isArray(value)) {
    return value.filter(Boolean).map((item) => String(item));
  }
  if (!value) {
    return [];
  }
  return [String(value)];
}

function extractFieldMeta(payloadValue) {
  if (!payloadValue || typeof payloadValue !== "object" || Array.isArray(payloadValue)) {
    return null;
  }

  const pageRaw = payloadValue.page;
  const page = Number.isFinite(Number(pageRaw)) ? Number(pageRaw) : null;

  return {
    bbox: payloadValue.bbox ?? null,
    page,
    confidence:
      typeof payloadValue.confidence === "number" ? payloadValue.confidence : null,
    bbox_relative:
      typeof payloadValue.bbox_relative === "boolean" ? payloadValue.bbox_relative : null,
    errors: asList(payloadValue.errors ?? payloadValue.error),
    isValid:
      typeof payloadValue.isValid === "boolean"
        ? payloadValue.isValid
        : typeof payloadValue.is_valid === "boolean"
        ? payloadValue.is_valid
        : null,
    status: payloadValue.status ?? payloadValue.validation_status ?? null,
    message:
      typeof payloadValue.message === "string"
        ? payloadValue.message
        : typeof payloadValue.validation_message === "string"
        ? payloadValue.validation_message
        : null,
  };
}

function mergeFieldNames(rawFields, normalizedFields, correctedFields) {
  const names = new Set([
    ...Object.keys(rawFields || {}),
    ...Object.keys(normalizedFields || {}),
    ...Object.keys(correctedFields || {}),
  ]);

  const priority = PRIORITY_FIELDS.filter((name) => names.has(name));
  const rest = [...names].filter((name) => !priority.includes(name)).sort();
  return [...priority, ...rest];
}

function pickInitialFieldValue(fieldName, rawFields, normalizedFields, correctedFields) {
  if (fieldName in correctedFields) {
    return readValue(correctedFields[fieldName]);
  }
  if (fieldName in normalizedFields) {
    return readValue(normalizedFields[fieldName]);
  }
  return readValue(rawFields[fieldName]);
}

function resolveHighlightStatus(meta) {
  const status = String(meta?.status || "").toLowerCase();
  if (status === "error") {
    return "error";
  }
  if (status === "invalid") {
    return "invalid";
  }
  if (Array.isArray(meta?.errors) && meta.errors.length > 0) {
    return "error";
  }
  if (meta?.isValid === false) {
    return "invalid";
  }
  if (typeof meta?.confidence === "number" && meta.confidence < 0.5) {
    return "invalid";
  }
  return "ok";
}

function renderBadge(kind) {
  if (kind === "corrected") {
    return <span className="review-badge corrected">corrected</span>;
  }
  return <span className="review-badge raw">raw</span>;
}

export default function ReviewPage({ documentId, onBack }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [fileName, setFileName] = useState("");
  const [status, setStatus] = useState("in_review");
  const [previewMeta, setPreviewMeta] = useState({
    available: false,
    file_type: null,
    page_count: 0,
  });
  const [previewPage, setPreviewPage] = useState(1);
  const [previewUrl, setPreviewUrl] = useState("");

  const [fieldNames, setFieldNames] = useState([]);
  const [fieldValues, setFieldValues] = useState({});
  const [fieldMeta, setFieldMeta] = useState({});
  const [rawFields, setRawFields] = useState({});
  const [normalizedFields, setNormalizedFields] = useState({});
  const [userCorrectedFields, setUserCorrectedFields] = useState({});

  const [saving, setSaving] = useState(false);
  const [info, setInfo] = useState("");

  // Backward-compat state that existing flow may rely on.
  const [activeField, setActiveField] = useState(null);

  const [highlightsState, setHighlightsState] = useState({
    highlights: [],
    selectedHighlightIds: [],
  });
  const { highlights, selectedHighlightIds } = highlightsState;

  const [autoZoomEnabled, setAutoZoomEnabled] = useState(AUTO_ZOOM_DEFAULT);
  const [zoomScale, setZoomScale] = useState(1);

  const viewerScrollRef = useRef(null);
  const imageRef = useRef(null);
  const [imageMetrics, setImageMetrics] = useState({
    displayWidth: 0,
    displayHeight: 0,
    naturalWidth: 0,
    naturalHeight: 0,
  });

  const clearHighlights = () => {
    setHighlightsState({ highlights: [], selectedHighlightIds: [] });
  };

  const buildHighlightForField = (fieldName) => {
    const meta = fieldMeta[fieldName];
    if (!meta) {
      return null;
    }

    const normalizedBBox = normalizeBBox(meta.bbox, meta.page || 1);
    if (!normalizedBBox) {
      return null;
    }

    const page = Number(normalizedBBox.page || meta.page || 1);
    const bbox = { ...normalizedBBox, page };
    const id = `${fieldName}:${page}:${bbox.x1}:${bbox.y1}:${bbox.x2}:${bbox.y2}`;

    return {
      id,
      fieldKey: fieldName,
      bbox,
      status: resolveHighlightStatus(meta),
      message: meta.message || meta.errors?.[0],
      createdAt: Date.now(),
    };
  };

  const updateSelectionFromField = (fieldName, isMultiSelect) => {
    const nextHighlight = buildHighlightForField(fieldName);

    setHighlightsState((prev) => {
      if (!ENHANCED_HIGHLIGHTS_ENABLED) {
        if (!nextHighlight) {
          return { highlights: [], selectedHighlightIds: [] };
        }
        return {
          highlights: [nextHighlight],
          selectedHighlightIds: [nextHighlight.id],
        };
      }

      if (!isMultiSelect) {
        if (!nextHighlight) {
          return { highlights: [], selectedHighlightIds: [] };
        }
        return {
          highlights: [nextHighlight],
          selectedHighlightIds: [nextHighlight.id],
        };
      }

      if (!nextHighlight) {
        return prev;
      }

      const wasSelected = prev.selectedHighlightIds.includes(nextHighlight.id);
      if (wasSelected) {
        const nextSelected = prev.selectedHighlightIds.filter((id) => id !== nextHighlight.id);
        return {
          highlights: prev.highlights.filter((item) => nextSelected.includes(item.id)),
          selectedHighlightIds: nextSelected,
        };
      }

      const filtered = prev.highlights.filter((item) => item.id !== nextHighlight.id);
      const nextHighlights = [...filtered, nextHighlight];
      const nextSelected = [...prev.selectedHighlightIds, nextHighlight.id];
      return { highlights: nextHighlights, selectedHighlightIds: nextSelected };
    });
  };

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError("");
    setInfo("");

    Promise.all([fetchReviewDocument(documentId), fetchReviewPreviewMeta(documentId)])
      .then(([docPayload, metaPayload]) => {
        if (!mounted) {
          return;
        }

        const raw = docPayload.raw_extracted_fields || {};
        const normalized = docPayload.normalized_fields || {};
        const corrected = docPayload.user_corrected_fields || {};

        const names = mergeFieldNames(raw, normalized, corrected);
        const values = {};
        const meta = {};

        for (const name of names) {
          values[name] = pickInitialFieldValue(name, raw, normalized, corrected);
          meta[name] =
            extractFieldMeta(corrected[name]) ||
            extractFieldMeta(normalized[name]) ||
            extractFieldMeta(raw[name]);
        }

        setFileName(docPayload.file_name || "");
        setStatus(docPayload.status || "in_review");
        setRawFields(raw);
        setNormalizedFields(normalized);
        setUserCorrectedFields(corrected);
        setFieldNames(names);
        setFieldValues(values);
        setFieldMeta(meta);
        setPreviewMeta(metaPayload || { available: false, file_type: null, page_count: 0 });
        setPreviewPage(1);
        setActiveField(null);
        clearHighlights();
        setZoomScale(1);
      })
      .catch((err) => {
        if (!mounted) {
          return;
        }
        setError(err?.response?.data?.detail || err.message || "Failed to load review data");
      })
      .finally(() => {
        if (mounted) {
          setLoading(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, [documentId]);

  useEffect(() => {
    if (!previewMeta.available) {
      setPreviewUrl("");
      return;
    }
    setPreviewUrl(buildReviewPreviewUrl(documentId, previewPage));
  }, [documentId, previewMeta, previewPage]);

  useEffect(() => {
    const onResize = () => {
      const imageNode = imageRef.current;
      if (!imageNode) {
        return;
      }
      const rect = imageNode.getBoundingClientRect();
      setImageMetrics((prev) => ({
        ...prev,
        displayWidth: rect.width,
        displayHeight: rect.height,
      }));
    };

    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
    };
  }, []);

  useEffect(() => {
    if (!previewUrl) {
      return;
    }
    const rafId = window.requestAnimationFrame(() => {
      const imageNode = imageRef.current;
      if (!imageNode) {
        return;
      }
      const rect = imageNode.getBoundingClientRect();
      setImageMetrics((prev) => ({
        ...prev,
        displayWidth: rect.width,
        displayHeight: rect.height,
      }));
    });

    return () => window.cancelAnimationFrame(rafId);
  }, [previewUrl, previewPage, zoomScale]);

  const visibleHighlights = useMemo(() => {
    const selected = highlights.filter((item) => selectedHighlightIds.includes(item.id));
    if (previewMeta.file_type !== "pdf") {
      return selected;
    }
    return selected.filter((item) => Number(item.bbox.page || 1) === previewPage);
  }, [highlights, previewMeta.file_type, previewPage, selectedHighlightIds]);

  const hasAnyBBox = useMemo(() => {
    return Object.values(fieldMeta).some((meta) =>
      Boolean(normalizeBBox(meta?.bbox, meta?.page || 1)),
    );
  }, [fieldMeta]);

  const overlayRects = useMemo(() => {
    if (!imageMetrics.displayWidth || !imageMetrics.displayHeight) {
      return [];
    }

    return visibleHighlights
      .map((item) => {
        const meta = fieldMeta[item.fieldKey] || {};
        const rect = bboxToRect(item.bbox, {
          displayWidth: imageMetrics.displayWidth,
          displayHeight: imageMetrics.displayHeight,
          naturalWidth: imageMetrics.naturalWidth,
          naturalHeight: imageMetrics.naturalHeight,
          bboxRelative: meta.bbox_relative,
        });
        return { item, rect };
      })
      .filter((entry) => entry.rect.width > 0 && entry.rect.height > 0);
  }, [fieldMeta, imageMetrics, visibleHighlights]);

  const primaryHighlight = useMemo(() => {
    if (selectedHighlightIds.length === 0) {
      return null;
    }
    const primaryId = selectedHighlightIds[selectedHighlightIds.length - 1];
    return highlights.find((item) => item.id === primaryId) || null;
  }, [highlights, selectedHighlightIds]);

  const primaryRect = useMemo(() => {
    if (!primaryHighlight || !imageMetrics.displayWidth || !imageMetrics.displayHeight) {
      return null;
    }

    const meta = fieldMeta[primaryHighlight.fieldKey] || {};
    return bboxToRect(primaryHighlight.bbox, {
      displayWidth: imageMetrics.displayWidth,
      displayHeight: imageMetrics.displayHeight,
      naturalWidth: imageMetrics.naturalWidth,
      naturalHeight: imageMetrics.naturalHeight,
      bboxRelative: meta.bbox_relative,
    });
  }, [fieldMeta, imageMetrics, primaryHighlight]);

  useEffect(() => {
    if (!ENHANCED_HIGHLIGHTS_ENABLED || !autoZoomEnabled || !hasAnyBBox) {
      return;
    }

    const container = viewerScrollRef.current;
    if (!container || !primaryRect) {
      return;
    }

    const targetZoom = computeZoomToFit(
      primaryRect,
      { width: container.clientWidth, height: container.clientHeight },
      20,
      1,
      3,
    );
    setZoomScale(targetZoom);
  }, [autoZoomEnabled, hasAnyBBox, primaryRect]);

  useEffect(() => {
    if (!ENHANCED_HIGHLIGHTS_ENABLED || !primaryRect || !hasAnyBBox) {
      return;
    }

    const container = viewerScrollRef.current;
    if (!container) {
      return;
    }

    const center = rectCenter(primaryRect);
    const nextTop = clamp(
      center.y - container.clientHeight / 2,
      0,
      Math.max(container.scrollHeight - container.clientHeight, 0),
    );
    const nextLeft = clamp(
      center.x - container.clientWidth / 2,
      0,
      Math.max(container.scrollWidth - container.clientWidth, 0),
    );

    container.scrollTo({ top: nextTop, left: nextLeft, behavior: "smooth" });
  }, [hasAnyBBox, primaryRect, previewPage, zoomScale]);

  useEffect(() => {
    if (!ENHANCED_HIGHLIGHTS_ENABLED || autoZoomEnabled) {
      return;
    }
    setZoomScale(1);
  }, [autoZoomEnabled]);

  const handleFocusField = (fieldName, event) => {
    setActiveField(fieldName);

    const meta = fieldMeta[fieldName];
    if (meta?.page && previewMeta.file_type === "pdf") {
      setPreviewPage((current) => {
        const nextPage = Number(meta.page);
        if (!Number.isFinite(nextPage) || nextPage < 1) {
          return current;
        }
        return current === nextPage ? current : nextPage;
      });
    }

    const isMultiSelect = Boolean(
      ENHANCED_HIGHLIGHTS_ENABLED && event && (event.metaKey || event.ctrlKey),
    );
    updateSelectionFromField(fieldName, isMultiSelect);
  };

  const handleChangeField = (fieldName, nextValue) => {
    setFieldValues((prev) => ({
      ...prev,
      [fieldName]: nextValue,
    }));
    setUserCorrectedFields((prev) => ({
      ...prev,
      [fieldName]: nextValue,
    }));
  };

  const buildNormalizedPayload = () => {
    const merged = { ...normalizedFields };
    for (const fieldName of fieldNames) {
      const meta = fieldMeta[fieldName] || {};
      merged[fieldName] = {
        value: fieldValues[fieldName] ?? "",
        bbox: meta.bbox ?? null,
        page: meta.page ?? 1,
        confidence: meta.confidence ?? null,
        bbox_relative: meta.bbox_relative ?? null,
      };
    }
    return merged;
  };

  const handleSave = async (nextStatus) => {
    setSaving(true);
    setError("");
    setInfo("");

    try {
      const nextNormalizedFields = buildNormalizedPayload();
      const payload = await saveReviewDocument({
        documentId,
        userCorrectedFields,
        normalizedFields: nextNormalizedFields,
        status: nextStatus,
      });

      const payloadRaw = payload.raw_extracted_fields || {};
      const payloadNormalized = payload.normalized_fields || {};
      const payloadCorrected = payload.user_corrected_fields || {};
      const nextNames = mergeFieldNames(
        payloadRaw,
        payloadNormalized,
        payloadCorrected,
      );

      const nextMeta = {};
      const nextValues = {};
      for (const name of nextNames) {
        nextValues[name] = pickInitialFieldValue(
          name,
          payloadRaw,
          payloadNormalized,
          payloadCorrected,
        );
        nextMeta[name] =
          extractFieldMeta(payloadCorrected[name]) ||
          extractFieldMeta(payloadNormalized[name]) ||
          extractFieldMeta(payloadRaw[name]);
      }

      setRawFields(payloadRaw);
      setNormalizedFields(payloadNormalized);
      setUserCorrectedFields(payloadCorrected);
      setFieldNames(nextNames);
      setFieldValues(nextValues);
      setFieldMeta(nextMeta);
      setStatus(payload.status || nextStatus);
      setInfo(nextStatus === "validated" ? "Document valide." : "Corrections sauvegardees.");
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const badgeByField = useMemo(() => {
    const result = {};
    for (const fieldName of fieldNames) {
      if (fieldName in userCorrectedFields) {
        result[fieldName] = "corrected";
      } else {
        result[fieldName] = "raw";
      }
    }
    return result;
  }, [fieldNames, userCorrectedFields]);

  if (loading) {
    return <section className="panel review-page">Loading review...</section>;
  }

  if (error && !fieldNames.length) {
    return (
      <section className="panel review-page">
        <p className="state error">Error: {error}</p>
        <button type="button" className="btn primary" onClick={onBack}>
          Retour
        </button>
      </section>
    );
  }

  return (
    <section className="panel review-page">
      <div className="review-header">
        <div>
          <h2>Review Document #{documentId}</h2>
          <p>{fileName}</p>
        </div>
        <div className="review-header-actions">
          <span className="review-status">Status: {status}</span>
          <button type="button" className="tab" onClick={onBack}>
            Retour
          </button>
        </div>
      </div>

      <div className="review-layout">
        <div className="review-viewer">
          <div className="review-viewer-topbar">
            <strong>Apercu</strong>
            <div className="review-viewer-controls">
              {ENHANCED_HIGHLIGHTS_ENABLED && hasAnyBBox && (
                <label className="review-toggle">
                  <input
                    type="checkbox"
                    checked={autoZoomEnabled}
                    onChange={(event) => setAutoZoomEnabled(event.target.checked)}
                  />
                  <span>Auto-zoom</span>
                </label>
              )}
              {ENHANCED_HIGHLIGHTS_ENABLED && hasAnyBBox && (
                <button
                  type="button"
                  className="tab"
                  onClick={clearHighlights}
                  disabled={selectedHighlightIds.length === 0}
                >
                  Clear ({selectedHighlightIds.length})
                </button>
              )}
              {ENHANCED_HIGHLIGHTS_ENABLED && !hasAnyBBox && (
                <span className="review-hint">No bbox data for this document.</span>
              )}
              {previewMeta.file_type === "pdf" && previewMeta.page_count > 1 && (
                <div className="review-page-controls">
                  <button
                    type="button"
                    className="tab"
                    onClick={() => setPreviewPage((page) => Math.max(1, page - 1))}
                    disabled={previewPage <= 1}
                  >
                    Page -
                  </button>
                  <span>
                    {previewPage}/{previewMeta.page_count}
                  </span>
                  <button
                    type="button"
                    className="tab"
                    onClick={() =>
                      setPreviewPage((page) =>
                        Math.min(previewMeta.page_count || 1, page + 1),
                      )
                    }
                    disabled={previewPage >= (previewMeta.page_count || 1)}
                  >
                    Page +
                  </button>
                </div>
              )}
            </div>
          </div>

          <div className="review-preview-frame" ref={viewerScrollRef}>
            {!previewMeta.available && (
              <p className="state">Aucun preview fichier disponible pour ce document.</p>
            )}
            {previewMeta.available && previewUrl && (
              <div
                className="review-image-wrap"
                style={{
                  width: `${Math.max(zoomScale, 1) * 100}%`,
                }}
              >
                <img
                  ref={imageRef}
                  src={previewUrl}
                  alt={`Preview document ${documentId}`}
                  className="review-image"
                  onLoad={(event) => {
                    const element = event.currentTarget;
                    const rect = element.getBoundingClientRect();
                    setImageMetrics({
                      naturalWidth: element.naturalWidth,
                      naturalHeight: element.naturalHeight,
                      displayWidth: rect.width,
                      displayHeight: rect.height,
                    });
                  }}
                />

                {overlayRects.map(({ item, rect }) => {
                  const isSelected = selectedHighlightIds.includes(item.id);
                  const shouldPulse = item.status === "error" || (item.status === "invalid" && isSelected);
                  return (
                    <div
                      key={`${item.id}-${item.createdAt}`}
                      className={`hl-box hl-${item.status} hl-fadein ${shouldPulse ? "hl-pulse" : ""}`}
                      title={item.message || item.fieldKey}
                      style={{
                        left: `${rect.left}px`,
                        top: `${rect.top}px`,
                        width: `${rect.width}px`,
                        height: `${rect.height}px`,
                      }}
                    />
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <div className="review-fields">
          {error && <p className="state error">Error: {error}</p>}
          {info && <p className="state">{info}</p>}

          <div className="review-fields-list">
            {fieldNames.map((fieldName) => {
              const meta = fieldMeta[fieldName];
              const isActive = activeField === fieldName;
              return (
                <article
                  key={fieldName}
                  className={`review-field-row ${isActive ? "active" : ""}`}
                  onClick={(event) => handleFocusField(fieldName, event)}
                >
                  <div className="review-field-row-head">
                    <strong>{fieldName}</strong>
                    {renderBadge(badgeByField[fieldName])}
                  </div>

                  <input
                    className="input"
                    value={fieldValues[fieldName] ?? ""}
                    onChange={(event) => handleChangeField(fieldName, event.target.value)}
                    onClick={(event) => event.stopPropagation()}
                  />

                  <div className="review-field-meta">
                    <button
                      type="button"
                      className="tab"
                      onClick={(event) => {
                        event.stopPropagation();
                        handleFocusField(fieldName, event);
                      }}
                    >
                      Focus
                    </button>
                    <span>
                      confidence: {meta?.confidence !== null && meta?.confidence !== undefined
                        ? `${Math.round(meta.confidence * 100)}%`
                        : "n/a"}
                    </span>
                    <span>page: {meta?.page || 1}</span>
                  </div>
                </article>
              );
            })}
          </div>

          <div className="review-actions-dock">
            <div className="review-actions">
              <button
                type="button"
                className="btn primary review-btn review-btn-save"
                onClick={() => handleSave("in_review")}
                disabled={saving}
              >
                {saving ? "Sauvegarde..." : "Sauvegarder corrections"}
              </button>
              <button
                type="button"
                className="btn primary review-btn review-btn-validate"
                onClick={() => handleSave("validated")}
                disabled={saving}
              >
                {saving ? "Validation..." : "Valider"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
