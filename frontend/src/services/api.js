import axios from "axios";

// Backend base URL can be overridden via VITE_API_BASE_URL.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000",
  timeout: 30000,
});

export async function uploadDocument(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await api.post("/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return response.data;
}

export async function fetchDocuments() {
  const response = await api.get("/documents");
  return response.data;
}

export async function processWithLlama({
  text,
  instruction,
  documentId,
  syncData = false,
}) {
  const response = await api.post(
    "/process_with_llama",
    {
      text,
      instruction,
      document_id: documentId ?? null,
      sync_data: Boolean(syncData),
    },
    {
      timeout: 300000,
    }
  );
  return response.data;
}

export async function saveDocumentData({ documentId, data, merge = true }) {
  const response = await api.put(
    `/documents/${documentId}/data`,
    {
      data,
      merge: Boolean(merge),
    },
    {
      timeout: 120000,
    }
  );
  return response.data;
}

export async function askDocumentQuestion({ documentId, question }) {
  const response = await api.post(
    `/documents/${documentId}/ask`,
    { question },
    { timeout: 180000 }
  );
  return response.data;
}
