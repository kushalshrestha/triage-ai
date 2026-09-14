import type { Token, TicketEventRead, TicketRead, UserRead } from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL;

let authToken: string | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (authToken) {
    headers.set("Authorization", `Bearer ${authToken}`);
  }
  if (options.body && !(options.body instanceof URLSearchParams)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${BASE_URL}${path}`, { ...options, headers });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // response body wasn't JSON; fall back to statusText
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function register(email: string, password: string): Promise<UserRead> {
  return request<UserRead>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function login(email: string, password: string): Promise<Token> {
  const body = new URLSearchParams({ username: email, password });
  return request<Token>("/auth/login", { method: "POST", body });
}

export function fetchCurrentUser(): Promise<UserRead> {
  return request<UserRead>("/auth/me");
}

export function listTickets(): Promise<TicketRead[]> {
  return request<TicketRead[]>("/tickets");
}

export function getTicket(ticketId: string): Promise<TicketRead> {
  return request<TicketRead>(`/tickets/${ticketId}`);
}

export function createTicket(subject: string, body: string): Promise<TicketRead> {
  return request<TicketRead>("/tickets", {
    method: "POST",
    body: JSON.stringify({ subject, body }),
  });
}

export function listTicketEvents(ticketId: string): Promise<TicketEventRead[]> {
  return request<TicketEventRead[]>(`/tickets/${ticketId}/events`);
}

export function addTicketComment(ticketId: string, body: string): Promise<TicketEventRead> {
  return request<TicketEventRead>(`/tickets/${ticketId}/events`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}
