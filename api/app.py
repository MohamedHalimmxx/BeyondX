"""
BeyondX API
===========
FastAPI application exposing the BrandGenius pipeline and
Content Creator Agent via Server-Sent Events (SSE).

Run with:
    python api/run.py
or:
    uvicorn api.app:app --reload --port 8000
"""

import sys
from pathlib import Path

# Make sure the project root is on sys.path so agents/ nodes/ etc. are importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routers import brand, content

app = FastAPI(
    title="BeyondX API",
    description="AI-powered brand intelligence pipeline",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/brand-packs", StaticFiles(directory="brand_packs"), name="brand-packs")

app.include_router(brand.router, prefix="/api/brand", tags=["brand"])
app.include_router(content.router, prefix="/api/content", tags=["content"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "BeyondX API"}