import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { addTicketComment, getTicket, listTicketEvents } from "../api/client";
import type { TicketEventRead, TicketRead } from "../api/types";

function describeEvent(event: TicketEventRead): string {
  switch (event.event_type) {
    case "created":
      return "Ticket created";
    case "comment_added":
      return typeof event.payload?.body === "string" ? event.payload.body : "Comment added";
    case "status_changed":
      return `Status changed: ${event.payload?.from} → ${event.payload?.to}`;
    default:
      return event.event_type;
  }
}

export function TicketDetailPage() {
  const { ticketId } = useParams<{ ticketId: string }>();
  const [ticket, setTicket] = useState<TicketRead | null>(null);
  const [events, setEvents] = useState<TicketEventRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [comment, setComment] = useState("");
  const [isSubmittingComment, setIsSubmittingComment] = useState(false);

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

  if (isLoading) return <p>Loading…</p>;
  if (error) return <p className="form-error">{error}</p>;
  if (!ticket) return <p>Ticket not found.</p>;

  return (
    <div className="page">
      <Link to="/tickets">&larr; Back to tickets</Link>
      <h1>{ticket.subject}</h1>
      <p className={`status status-${ticket.status}`}>{ticket.status}</p>
      <p>{ticket.body}</p>

      <h2>Activity</h2>
      <ul className="event-list">
        {events.map((event) => (
          <li key={event.id}>
            <span className="muted">{new Date(event.created_at).toLocaleString()}</span>
            <p>{describeEvent(event)}</p>
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
