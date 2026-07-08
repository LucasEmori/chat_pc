"""Servidor FastAPI da AzimeAI.

Substitui o entrypoint Streamlit (`streamlit run app.py`). Serve:
- `/api/*`        → rotas REST/SSE (api/routes.py)
- `/` (restante)  → frontend estático (static/index.html, css, js, assets)

Run (dev):  uvicorn server:app --reload
Run (prod): uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router as api_router
from api.sessions import sessions

load_dotenv()

# Provider fixo: Google Gemini. Sem selecao pelo usuario.
os.environ["LLM_PROVIDER"] = "google"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("azimeai")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="AzimeAI", docs_url="/api/docs", openapi_url="/api/openapi.json")

# Rotas da API primeiro (prefixo /api).
app.include_router(api_router)


@app.on_event("shutdown")
def _shutdown() -> None:
    sessions.shutdown()
    logger.info("Servidor encerrado.")


# Rota raiz → index.html (antes do mount catch-all).
@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# Fallback: tudo que não for /api/* vira arquivo estático.
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
