from fastapi import FastAPI

from app.routers import auth, tickets

app = FastAPI(title="TriageAI", version="0.1.0")

app.include_router(auth.router)
app.include_router(tickets.router)


@app.get("/health")
def health():
    """Liveness check. Extend later with DB and Ollama reachability checks."""
    return {"status": "ok"}


# The agent router gets wired up once phase 5 (agent orchestration) lands:
# from app.routers import agent
# app.include_router(agent.router)
