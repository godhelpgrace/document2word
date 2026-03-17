"""
FastAPI application entry point.
"""

import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logging.getLogger(__name__).info("Document-AI API starting up...")
    logging.getLogger(__name__).info(f"Upload dir: {settings.UPLOAD_DIR}")
    logging.getLogger(__name__).info(f"Result dir: {settings.RESULT_DIR}")
    yield
    logging.getLogger(__name__).info("Document-AI API shutting down...")


app = FastAPI(
    title="Document-AI",
    description="PDF 智能识别与可编辑 Word 转换引擎",
    version="0.1.0",
    lifespan=lifespan,
)

# Static UI
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "UI not found"}

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.1.0"}
