// Hand-mirrored from backend/app/schemas/{user,ticket}.py — see ADR-0006
// for why this isn't codegen'd yet. Keep in sync manually when those
// schemas change.

export type UserRole = "customer" | "agent" | "admin";

export interface UserRead {
  id: string;
  email: string;
  role: UserRole;
}

export interface Token {
  access_token: string;
  token_type: string;
}

export type TicketStatus = "open" | "pending" | "resolved" | "closed" | "escalated";

export interface TicketRead {
  id: string;
  requester_id: string;
  assigned_agent_id: string | null;
  subject: string;
  body: string;
  status: TicketStatus;
  created_at: string;
  updated_at: string;
}

export type TicketEventType =
  | "created"
  | "comment_added"
  | "status_changed"
  | "draft_generated"
  | "escalated"
  | "resolved";

export interface TicketEventRead {
  id: string;
  ticket_id: string;
  actor_id: string | null;
  event_type: TicketEventType;
  payload: Record<string, unknown> | null;
  created_at: string;
}
