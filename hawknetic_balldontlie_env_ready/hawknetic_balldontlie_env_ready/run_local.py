from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HAWKNETIC_HOST") or os.getenv("HOST") or ("0.0.0.0" if os.getenv("PORT") else "127.0.0.1")
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
