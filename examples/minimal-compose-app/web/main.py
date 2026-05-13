import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse


APP_NAME = os.getenv("APP_NAME", "my-compose-app")
DEGRADED = False

app = FastAPI(title="Minimal Compose App")


@app.get("/", response_class=HTMLResponse)
def home():
    status = "degraded" if DEGRADED else "healthy"
    return f"""
    <!doctype html>
    <html lang="en">
      <head><title>Minimal Compose App</title></head>
      <body style="font-family: system-ui; margin: 40px;">
        <h1>Minimal Compose App</h1>
        <p>Status: <strong>{status}</strong></p>
      </body>
    </html>
    """


@app.get("/health")
def health():
    return {"service": APP_NAME, "status": "unhealthy" if DEGRADED else "healthy"}


@app.get("/api/ready")
def ready():
    return {"ready": not DEGRADED}


@app.post("/runtime/restart")
def restart():
    global DEGRADED
    DEGRADED = False
    return {"status": "restarted", "service": APP_NAME}


@app.post("/runtime/degrade")
def degrade():
    global DEGRADED
    DEGRADED = True
    return {"status": "degraded", "service": APP_NAME}
