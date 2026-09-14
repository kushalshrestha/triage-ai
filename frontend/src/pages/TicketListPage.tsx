import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { createTicket, listTickets } from "../api/client";
import type { TicketRead } from "../api/types";
import { useAuth } from "../auth/AuthContext";

export function TicketListPage() {
  const { user, logout } = useAuth();
  const isStaff = user?.role === "agent" || user?.role === "admin";
  const [tickets, setTickets] = useState<TicketRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  function refresh() {
    setIsLoading(true);
    listTickets()
      .then(setTickets)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load tickets"))
      .finally(() => setIsLoading(false));
  }

  useEffect(refresh, []);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setIsCreating(true);
    try {
      await createTicket(subject, body);
      setSubject("");
      setBody("");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create ticket");
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>{isStaff ? "All tickets" : "Your tickets"}</h1>
        <div>
          {isStaff && <Link to="/knowledge">Knowledge base</Link>}
          <span className="muted">{user?.email}</span>
          <button onClick={logout}>Log out</button>
        </div>
      </header>

      {!isStaff && (
        <form onSubmit={handleCreate} className="new-ticket-form">
          <h2>New ticket</h2>
          <label>
            Subject
            <input value={subject} onChange={(e) => setSubject(e.target.value)} required />
          </label>
          <label>
            Description
            <textarea value={body} onChange={(e) => setBody(e.target.value)} required rows={3} />
          </label>
          <button type="submit" disabled={isCreating}>
            {isCreating ? "Creating…" : "Create ticket"}
          </button>
        </form>
      )}

      {error && <p className="form-error">{error}</p>}

      {isLoading ? (
        <p>Loading…</p>
      ) : tickets.length === 0 ? (
        <p className="muted">No tickets yet.</p>
      ) : (
        <ul className="ticket-list">
          {tickets.map((ticket) => (
            <li key={ticket.id}>
              <span className="ticket-list-main">
                <Link to={`/tickets/${ticket.id}`}>{ticket.subject}</Link>
                {isStaff && <span className="muted">{ticket.requester_email}</span>}
              </span>
              <span className={`status status-${ticket.status}`}>{ticket.status}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
