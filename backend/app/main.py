from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.config import get_settings
from app.routers import agent, auth, knowledge, tickets
from app.tracing import setup_tracing

setup_tracing()

app = FastAPI(title="TriageAI", version="0.1.0")

# Auto-creates the root span for every HTTP request (e.g. POST
# /tickets/{ticket_id}/triage) — the parent of every span added
# manually in app/agent/, via OTel's automatic context propagation.
# See ADR-0030.
FastAPIInstrumentor.instrument_app(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(knowledge.router)
app.include_router(agent.router)


@app.get("/health")
def health():
    """Liveness check. Extend later with DB and Ollama reachability checks."""
    return {"status": "ok"}
