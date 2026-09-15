import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { addTicketComment, getTicket, listTicketEvents, triggerTriage, updateTicketStatus } from "../api/client";
import type { AgentDecisionRead, TicketEventRead, TicketRead, TicketStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const TICKET_STATUSES: TicketStatus[] = ["open", "pending", "resolved", "closed", "escalated"];

function EventBody({ event }: { event: TicketEventRead }) {
  switch (event.event_type) {
    case "created":
      return <p>Ticket created</p>;
    case "comment_added":
      return <p>{typeof event.payload?.body === "string" ? event.payload.body : "Comment added"}</p>;
    case "status_changed":
      return (
        <p>
          Status changed: {String(event.payload?.from)} → {String(event.payload?.to)}
        </p>
      );
    case "draft_generated": {
      const replyText = typeof event.payload?.reply_text === "string" ? event.payload.reply_text : "";
      const grounded = event.payload?.grounded;
      const citedCount = Array.isArray(event.payload?.cited_chunk_indices)
        ? event.payload.cited_chunk_indices.length
        : 0;
      return (
        <div className="draft-event">
          <p className="draft-event-meta">
            <strong>AI drafted a reply</strong>
            {typeof grounded === "boolean" && (
              <span className={`badge ${grounded ? "badge-grounded" : "badge-ungrounded"}`}>
                {grounded ? "grounded ✓" : "ungrounded ✗"}
              </span>
            )}
            <span className="muted">
              {citedCount} source{citedCount === 1 ? "" : "s"} cited
            </span>
          </p>
          <p className="draft-event-text">{replyText}</p>
        </div>
      );
    }
    case "escalated":
      return <p>Escalated to a human agent</p>;
    case "resolved":
      return <p>Marked resolved</p>;
    default:
      return <p>{event.event_type}</p>;
  }
}

export function TicketDetailPage() {
  const { ticketId } = useParams<{ ticketId: string }>();
  const { user } = useAuth();
  const isStaff = user?.role === "agent" || user?.role === "admin";

  const [ticket, setTicket] = useState<TicketRead | null>(null);
  const [events, setEvents] = useState<TicketEventRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [comment, setComment] = useState("");
  const [isSubmittingComment, setIsSubmittingComment] = useState(false);

  const [isTriaging, setIsTriaging] = useState(false);
  const [lastDecision, setLastDecision] = useState<AgentDecisionRead | null>(null);
  const [isUpdatingTicket, setIsUpdatingTicket] = useState(false);

  function refresh() {
    if (!ticketId) return;
    setIsLoading(true);
    Promise.all([getTicket(ticketId), listTicketEvents(ticketId)])
      .then(([ticketData, eventsData]) => {
        setTicket(ticketData);
        setEvents(eventsData);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load ticket"))
      .finally(() => setIsLoading(false));
  }

  useEffect(refresh, [ticketId]);

  async function handleAddComment(event: FormEvent) {
    event.preventDefault();
    if (!ticketId) return;
    setIsSubmittingComment(true);
    try {
      await addTicketComment(ticketId, comment);
      setComment("");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add comment");
    } finally {
      setIsSubmittingComment(false);
    }
  }

  async function handleTriage() {
    if (!ticketId) return;
    setError(null);
    setIsTriaging(true);
    try {
      const decision = await triggerTriage(ticketId);
      setLastDecision(decision);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Triage failed");
    } finally {
      setIsTriaging(false);
    }
  }

  async function handleStatusChange(newStatus: TicketStatus) {
    if (!ticketId) return;
    setError(null);
    setIsUpdatingTicket(true);
    try {
      setTicket(await updateTicketStatus(ticketId, { status: newStatus }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setIsUpdatingTicket(false);
    }
  }

  async function handleAssignToMe() {
    if (!ticketId || !user) return;
    setError(null);
    setIsUpdatingTicket(true);
    try {
      setTicket(await updateTicketStatus(ticketId, { assigned_agent_id: user.id }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to assign ticket");
    } finally {
      setIsUpdatingTicket(false);
    }
  }

  if (isLoading) return <p>Loading…</p>;
  if (error) return <p className="form-error">{error}</p>;
  if (!ticket) return <p>Ticket not found.</p>;

  return (
    <div className="page">
      <Link to="/tickets">&larr; Back to tickets</Link>
      <h1>{ticket.subject}</h1>
      <p className={`status status-${ticket.status}`}>{ticket.status}</p>
      {isStaff && <p className="muted">From: {ticket.requester_email}</p>}
      <p>{ticket.body}</p>

      {isStaff && (
        <div className="staff-panel">
          <h2>Agent tools</h2>
          <div className="staff-panel-row">
            <label>
              Status
              <select
                value={ticket.status}
                onChange={(e) => handleStatusChange(e.target.value as TicketStatus)}
                disabled={isUpdatingTicket}
              >
                {TICKET_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={handleAssignToMe}
              disabled={isUpdatingTicket || ticket.assigned_agent_id === user?.id}
            >
              {ticket.assigned_agent_id === user?.id ? "Assigned to you" : "Assign to me"}
            </button>
            <button onClick={handleTriage} disabled={isTriaging}>
              {isTriaging ? "Running triage…" : "Run AI Triage"}
            </button>
          </div>

          {lastDecision && (
            <div className="decision-panel">
              <p>
                <strong>Decision:</strong> {lastDecision.decision_type}
                {lastDecision.confidence_score !== null && (
                  <span className="muted"> (confidence {lastDecision.confidence_score.toFixed(2)})</span>
                )}
              </p>
              {lastDecision.reasoning && <p className="muted">{lastDecision.reasoning}</p>}
            </div>
          )}
        </div>
      )}

      <h2>Activity</h2>
      <ul className="event-list">
        {events.map((event) => (
          <li key={event.id}>
            <span className="muted">{new Date(event.created_at).toLocaleString()}</span>
            <EventBody event={event} />
          </li>
        ))}
      </ul>

      <form onSubmit={handleAddComment} className="comment-form">
        <label>
          Add a comment
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} required rows={3} />
        </label>
        <button type="submit" disabled={isSubmittingComment}>
          {isSubmittingComment ? "Posting…" : "Post comment"}
        </button>
      </form>
    </div>
  );
}
