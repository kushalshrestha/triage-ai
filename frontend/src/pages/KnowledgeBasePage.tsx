import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router-dom";

import {
  approveKnowledgeDoc,
  createKnowledgeDoc,
  deleteKnowledgeDoc,
  listKnowledgeDocs,
  rejectKnowledgeDoc,
  searchKnowledge,
} from "../api/client";
import type { ChunkSearchResult, KnowledgeDocRead } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const STATUS_LABELS: Record<string, string> = {
  processing: "Processing…",
  pending_review: "Pending review",
  approved: "Approved",
  rejected: "Rejected",
  failed: "Failed",
};

export function KnowledgeBasePage() {
  const { user } = useAuth();
  const isStaff = user?.role === "agent" || user?.role === "admin";
  const isAdmin = user?.role === "admin";

  const [docs, setDocs] = useState<KnowledgeDocRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [source, setSource] = useState("");
  const [content, setContent] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<ChunkSearchResult[] | null>(null);
  const [isSearching, setIsSearching] = useState(false);

  function refresh() {
    setIsLoading(true);
    listKnowledgeDocs()
      .then(setDocs)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load knowledge base"))
      .finally(() => setIsLoading(false));
  }

  useEffect(refresh, []);

  if (!isStaff) {
    return <Navigate to="/tickets" replace />;
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setIsCreating(true);
    try {
      await createKnowledgeDoc(title, source, content);
      setTitle("");
      setSource("");
      setContent("");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add document");
    } finally {
      setIsCreating(false);
    }
  }

  async function handleDelete(docId: string) {
    setError(null);
    try {
      await deleteKnowledgeDoc(docId);
      setConfirmDeleteId(null);
      if (expandedId === docId) setExpandedId(null);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete document");
    }
  }

  async function handleApprove(docId: string) {
    setError(null);
    try {
      await approveKnowledgeDoc(docId);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve document");
    }
  }

  async function handleReject(docId: string) {
    setError(null);
    try {
      await rejectKnowledgeDoc(docId);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reject document");
    }
  }

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setIsSearching(true);
    try {
      setSearchResults(await searchKnowledge(query));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setIsSearching(false);
    }
  }

  return (
    <div className="page">
      <Link to="/tickets">&larr; Back to tickets</Link>
      <h1>Knowledge base</h1>

      {error && <p className="form-error">{error}</p>}

      <form onSubmit={handleCreate} className="new-ticket-form">
        <h2>Add document</h2>
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} required />
        </label>
        <label>
          Source (optional)
          <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="e.g. faq" />
        </label>
        <label>
          Content
          <textarea value={content} onChange={(e) => setContent(e.target.value)} required rows={4} />
        </label>
        <button type="submit" disabled={isCreating}>
          {isCreating ? "Adding…" : "Add document"}
        </button>
      </form>

      <form onSubmit={handleSearch} className="new-ticket-form">
        <h2>Test search</h2>
        <label>
          Query
          <input value={query} onChange={(e) => setQuery(e.target.value)} required />
        </label>
        <button type="submit" disabled={isSearching}>
          {isSearching ? "Searching…" : "Search"}
        </button>
        {searchResults && (
          <ul className="search-result-list">
            {searchResults.length === 0 && <li className="muted">No results.</li>}
            {searchResults.map((r) => (
              <li key={r.chunk_id} className="search-result">
                <p className="draft-event-meta">
                  <strong>{r.knowledge_doc_title}</strong>
                  <span className="muted">similarity {r.similarity_score.toFixed(2)}</span>
                </p>
                <p>{r.content}</p>
              </li>
            ))}
          </ul>
        )}
      </form>

      <h2>Documents</h2>
      {isLoading ? (
        <p>Loading…</p>
      ) : docs.length === 0 ? (
        <p className="muted">No documents yet.</p>
      ) : (
        <ul className="knowledge-doc-list">
          {docs.map((doc) => (
            <li key={doc.id} className="knowledge-doc-item">
              <div className="knowledge-doc-row">
                <span className="ticket-list-main">
                  <strong>{doc.title}</strong>
                  <span className="muted">
                    {doc.source ? `${doc.source} · ` : ""}
                    {STATUS_LABELS[doc.status] ?? doc.status} ·{" "}
                    {new Date(doc.created_at).toLocaleString()}
                  </span>
                </span>
                <span className="staff-panel-row">
                  {isAdmin && doc.status === "pending_review" && (
                    <>
                      <button onClick={() => handleApprove(doc.id)}>Approve</button>
                      <button onClick={() => handleReject(doc.id)}>Reject</button>
                    </>
                  )}
                  <button onClick={() => setExpandedId(expandedId === doc.id ? null : doc.id)}>
                    {expandedId === doc.id ? "Hide" : "View"}
                  </button>
                  {confirmDeleteId === doc.id ? (
                    <>
                      <span className="muted">Delete permanently? This also removes it from past decisions' history.</span>
                      <button onClick={() => handleDelete(doc.id)}>Confirm delete</button>
                      <button onClick={() => setConfirmDeleteId(null)}>Cancel</button>
                    </>
                  ) : (
                    <button onClick={() => setConfirmDeleteId(doc.id)}>Delete</button>
                  )}
                </span>
              </div>
              {expandedId === doc.id && <p className="draft-event-text">{doc.content}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
