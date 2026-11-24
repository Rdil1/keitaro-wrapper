from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.keitaro import KeitaroError

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Keitaro wrapper", version="1.0.0")
app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(KeitaroError)
async def keitaro_error_handler(_: Request, exc: KeitaroError):
    # 4xx от Keitaro (кроме проблем с ключом) отдаём как есть — это ошибка в данных запроса.
    if 400 <= exc.status < 500 and exc.status not in (401, 403):
        status = exc.status
        detail = exc.message
    elif exc.status in (401, 403):
        status = 502
        detail = "Keitaro rejected the API key: check KEITARO_API_KEY in .env"
    else:
        status = 502
        detail = exc.message
    return JSONResponse(status_code=status, content={"detail": detail, "keitaro": exc.payload})


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
