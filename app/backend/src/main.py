from __future__ import annotations

import uvicorn

from .settings import settings


def main():
    uvicorn.run("app.backend.src.main:app", host=settings.host, port=settings.port,
                reload=False, log_level="info")


# uvicorn imports this module to find `app`; expose it.
from .app import app  # noqa: E402,F401

if __name__ == "__main__":
    main()