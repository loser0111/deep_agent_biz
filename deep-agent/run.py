#!/usr/bin/env python3
"""本地启动脚本：python run.py"""

from __future__ import annotations

import uvicorn

from app.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        reload_dirs=["app"],
    )
