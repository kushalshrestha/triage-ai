from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, knowledge, tickets

app = FastAPI(title="TriageAI", version="0.1.0")

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


@app.get("/health")
def health():
    """Liveness check. Extend later with DB and Ollama reachability checks."""
    return {"status": "ok"}


# The agent router gets wired up once phase 5 (agent orchestration) lands:
# from app.routers import agent
# app.include_router(agent.router)
