import axios from "axios";

const reviewApi = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000",
  timeout: 120000,
});

export async function fetchReviewDocument(documentId) {
  const response = await reviewApi.get(`/review/documents/${documentId}`);
  return response.data;
}

export async function fetchReviewPreviewMeta(documentId) {
  const response = await reviewApi.get(`/review/documents/${documentId}/preview/meta`);
  return response.data;
}

export function buildReviewPreviewUrl(documentId, page = 1) {
  const baseURL = reviewApi.defaults.baseURL || "";
  const ts = Date.now();
  return `${baseURL}/review/documents/${documentId}/preview?page=${page}&_=${ts}`;
}

export async function requestReviewSuggestions({ documentId, fields, mode }) {
  const response = await reviewApi.post(`/review/normalize`, {
    document_id: documentId,
    fields,
    mode,
  });
  return response.data;
}

export async function saveReviewDocument({
  documentId,
  userCorrectedFields,
  normalizedFields,
  status,
}) {
  const response = await reviewApi.put(`/review/documents/${documentId}`, {
    user_corrected_fields: userCorrectedFields,
    normalized_fields: normalizedFields,
    status,
  });
  return response.data;
}
