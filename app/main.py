"""
Punto de entrada ASGI para Docker.

La aplicación FastAPI vive en `backend.main`; aquí solo reexportamos `app`
para cumplir el comando `uvicorn app.main:app`.
"""

from backend.main import app

__all__ = ["app"]
