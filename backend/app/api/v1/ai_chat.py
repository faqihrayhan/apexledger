"""
AI Chat API routes (placeholder for Phase 4).

The AI sidebar endpoints will be implemented after the core accounting
engine (GL, HR, Inventory) is functional.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/ai", tags=["AI Assistant"])


@router.get("/health")
async def ai_health():
    """Simple health-check endpoint for the AI module."""
    return {"module": "ai_assistant", "status": "ok"}
