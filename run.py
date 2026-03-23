#!/usr/bin/env python3
"""
Run the dev server with one command:

    python run.py

Hot-reload is on by default.
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,        # auto-restart on file save
        reload_dirs=["app"],
        log_level="debug",
    )

