import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "./config";

type DocumentInfo = {
  id: number;
  name: string;
  doc_type: string;
  chunk_count: number;
  created_at: string;
  category: string | null;
  case_number: string | null;
  court: string | null;
  parties: string | null;
  decision_date: string | null;
};

type CategoryInfo = {
  id: number;
  name: string;
};

const DOC_TYPE_LABELS: Record<string, string> = {
  guideline: "הנחיה",
  example: "מסמך לדוגמה",
  precedent: "תקדים",
};

function DocumentsPanel() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [categories, setCategories] = useState<CategoryInfo[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [docType, setDocType] = useState("auto");
  const [uploadCategory, setUploadCategory] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [newCategory, setNewCategory] = useState("");
  const [showCategories, setShowCategories] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const query = filterCategory
        ? `?category=${encodeURIComponent(filterCategory)}`
        : "";
      const response = await apiFetch(`/api/documents${query}`);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail ?? "Request failed");
      }
      setDocuments(data as DocumentInfo[]);
      setError(null);
    } catch (refreshError) {
      setError(
        refreshError instanceof Error && refreshError.message
          ? refreshError.message
          : "שגיאה בטעינת רשימת המסמכים.",
      );
    }
  }, [filterCategory]);

  const refreshCategories = useCallback(async () => {
    try {
      const response = await apiFetch("/api/categories");
      if (response.ok) {
        setCategories((await response.json()) as CategoryInfo[]);
      }
    } catch {
      // ignore — categories stay empty
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    void refreshCategories();
  }, [refreshCategories]);

  const upload = async () => {
    if (!selectedFile || busy) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", selectedFile);
      form.append("doc_type", docType);
      form.append("category", uploadCategory);

      const response = await apiFetch("/api/documents", {
        method: "POST",
        body: form,
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail ?? "Upload failed");
      }
      setSelectedFile(null);
      setFileInputKey((key) => key + 1);
      await refresh();
    } catch (uploadError) {
      setError(
        uploadError instanceof Error && uploadError.message
          ? uploadError.message
          : "שגיאה בהעלאת המסמך.",
      );
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const response = await apiFetch(`/api/documents/${id}`, {
        method: "DELETE",
      });
      if (!response.ok && response.status !== 404) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.detail ?? "Delete failed");
      }
      await refresh();
    } catch (deleteError) {
      setError(
        deleteError instanceof Error && deleteError.message
          ? deleteError.message
          : "שגיאה במחיקת המסמך.",
      );
    } finally {
      setBusy(false);
    }
  };

  const patchDocument = async (
    id: number,
    fields: Partial<Pick<DocumentInfo, "doc_type" | "category">>,
  ) => {
    try {
      const response = await apiFetch(`/api/documents/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.detail ?? "Update failed");
      }
      await refresh();
    } catch (patchError) {
      setError(
        patchError instanceof Error && patchError.message
          ? patchError.message
          : "שגיאה בעדכון המסמך.",
      );
    }
  };

  const addCategory = async () => {
    const name = newCategory.trim();
    if (!name) return;
    try {
      const response = await apiFetch("/api/categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.detail ?? "Create failed");
      }
      setNewCategory("");
      await refreshCategories();
    } catch (createError) {
      setError(
        createError instanceof Error && createError.message
          ? createError.message
          : "שגיאה בהוספת קטגוריה.",
      );
    }
  };

  const removeCategory = async (id: number) => {
    try {
      await apiFetch(`/api/categories/${id}`, { method: "DELETE" });
      await refreshCategories();
      await refresh();
    } catch {
      // ignore
    }
  };

  return (
    <div className="documents">
      <div className="upload-row">
        <input
          key={fileInputKey}
          type="file"
          accept=".pdf,.docx,.txt,.md"
          onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
        />
        <select
          value={docType}
          onChange={(event) => setDocType(event.target.value)}
          aria-label="סוג מסמך"
        >
          <option value="auto">סוג: אוטומטי</option>
          {Object.entries(DOC_TYPE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <select
          value={uploadCategory}
          onChange={(event) => setUploadCategory(event.target.value)}
          aria-label="קטגוריה"
        >
          <option value="">קטגוריה: אוטומטי</option>
          {categories.map((category) => (
            <option key={category.id} value={category.name}>
              {category.name}
            </option>
          ))}
        </select>
        <button onClick={() => void upload()} disabled={busy || !selectedFile}>
          {busy ? "מעבד..." : "העלה למאגר"}
        </button>
      </div>
      <div className="upload-row">
        <select
          value={filterCategory}
          onChange={(event) => setFilterCategory(event.target.value)}
          aria-label="סינון לפי קטגוריה"
        >
          <option value="">כל הקטגוריות</option>
          {categories.map((category) => (
            <option key={category.id} value={category.name}>
              {category.name}
            </option>
          ))}
        </select>
        <button
          className="chip"
          onClick={() => setShowCategories((value) => !value)}
        >
          ניהול קטגוריות
        </button>
      </div>
      {showCategories && (
        <div className="category-manager">
          {categories.map((category) => (
            <span key={category.id} className="doc-type category-pill">
              {category.name}
              <button
                className="conv-delete"
                aria-label={`מחק קטגוריה ${category.name}`}
                onClick={() => void removeCategory(category.id)}
              >
                ✕
              </button>
            </span>
          ))}
          <input
            className="text-input category-input"
            placeholder="קטגוריה חדשה"
            value={newCategory}
            onChange={(event) => setNewCategory(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && void addCategory()}
          />
          <button onClick={() => void addCategory()}>הוסף</button>
        </div>
      )}
      {error && <div className="error-text">{error}</div>}
      <div className="doc-list">
        {documents.length === 0 && !error && (
          <div className="doc-empty">
            המאגר ריק. העלה הנחיות, מסמכים לדוגמה, תקדימים ופסקי דין כדי שהסוכן
            יתבסס עליהם.
          </div>
        )}
        {documents.map((document) => (
          <div key={document.id} className="doc-row">
            <div className="doc-main">
              <span className="doc-name">{document.name}</span>
              {document.doc_type === "precedent" &&
                (document.case_number || document.court || document.decision_date) && (
                  <span className="doc-meta">
                    {[document.case_number, document.parties, document.court, document.decision_date]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                )}
              <span className="doc-meta">
                {document.chunk_count} קטעים ·{" "}
                {new Date(document.created_at).toLocaleDateString("he-IL")}
              </span>
            </div>
            <select
              className="doc-select"
              value={document.doc_type}
              aria-label="שינוי סוג"
              onChange={(event) =>
                void patchDocument(document.id, { doc_type: event.target.value })
              }
            >
              {Object.entries(DOC_TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <select
              className="doc-select"
              value={document.category ?? ""}
              aria-label="שינוי קטגוריה"
              onChange={(event) =>
                void patchDocument(document.id, {
                  category: event.target.value || null,
                })
              }
            >
              <option value="">ללא קטגוריה</option>
              {categories.map((category) => (
                <option key={category.id} value={category.name}>
                  {category.name}
                </option>
              ))}
            </select>
            <button
              className="danger"
              onClick={() => void remove(document.id)}
              disabled={busy}
              aria-label={`מחק את ${document.name}`}
            >
              מחק
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

export default DocumentsPanel;
