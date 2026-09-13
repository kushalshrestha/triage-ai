from fastapi import FastAPI

app = FastAPI(title="TriageAI", version="0.1.0")


@app.get("/health")
def health():
    """Liveness check. Extend later with DB and Ollama reachability checks."""
    return {"status": "ok"}


# Routers get wired up as each phase lands:
# from app.routers import tickets, agent
# app.include_router(tickets.router)
# app.include_router(agent.router)
