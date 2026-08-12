"""
Dashboard Runner — Tahap 11.
Jalankan UI dashboard di localhost:8000.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.web.main:app", host="0.0.0.0", port=8000, reload=True)