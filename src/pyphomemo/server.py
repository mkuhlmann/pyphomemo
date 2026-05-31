"""FastAPI server: print API, in-memory job queue, status, and HTML index."""

from __future__ import annotations

import asyncio
import io
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import imaging, printer, protocol


def _templates_dir() -> Path:
    """Locate the templates dir, both in-tree and inside a PyInstaller bundle."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "pyphomemo" / "templates"
    return Path(__file__).parent / "templates"


TEMPLATES = Jinja2Templates(directory=str(_templates_dir()))

JobStatus = Literal["queued", "printing", "done", "error"]


@dataclass
class Job:
    id: int
    type: Literal["text", "image"]
    label: str
    status: JobStatus = "queued"
    created: float = field(default_factory=time.time)
    started: Optional[float] = None
    finished: Optional[float] = None
    error: Optional[str] = None
    width: int = protocol.PRINTER_WIDTH_PX
    height: int = 0
    # Pre-rendered raster + print settings, filled at enqueue time.
    raster: bytes = b""
    speed: int = protocol.DEFAULT_SPEED
    density: int = protocol.DEFAULT_DENSITY
    media: int = protocol.DEFAULT_MEDIA

    def public(self) -> dict:
        d = asdict(self)
        d.pop("raster", None)
        return d


class JobQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._jobs: dict[int, Job] = {}
        self._next_id = 1
        self._worker: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def add(self, job_kwargs: dict) -> Job:
        async with self._lock:
            job = Job(id=self._next_id, **job_kwargs)
            self._next_id += 1
            self._jobs[job.id] = job
        await self._queue.put(job.id)
        return job

    def get(self, job_id: int) -> Optional[Job]:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.id, reverse=True)

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    async def _run(self) -> None:
        while True:
            job_id = await self._queue.get()
            job = self._jobs.get(job_id)
            if job is None:
                continue
            job.status = "printing"
            job.started = time.time()
            try:
                await printer.print_raster(
                    None,
                    job.raster,
                    job.height,
                    width_bytes=job.width // 8,
                    speed=job.speed,
                    density=job.density,
                    media=job.media,
                )
                job.status = "done"
            except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
                job.status = "error"
                job.error = str(exc)
            finally:
                job.finished = time.time()
                self._queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.queue = JobQueue()
    app.state.queue.start()
    try:
        yield
    finally:
        await app.state.queue.stop()


app = FastAPI(title="Phomemo M110 Print Server", lifespan=lifespan)


def _queue(request: Request) -> JobQueue:
    return request.app.state.queue


class TextJobRequest(BaseModel):
    text: str
    label: str = "40x30"  # WxH in mm
    font_size: int = 32
    align: str = "left"
    density: int = protocol.DEFAULT_DENSITY
    speed: int = protocol.DEFAULT_SPEED
    media: int = protocol.DEFAULT_MEDIA


@app.post("/api/print/text")
async def api_print_text(req: TextJobRequest, request: Request):
    try:
        width_px = imaging.label_to_px(req.label)[0]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    raster, height, _ = imaging.text_to_raster(
        req.text, width=width_px, font_size=req.font_size, align=req.align
    )
    job = await _queue(request).add(
        dict(
            type="text",
            label=req.text.splitlines()[0][:40] if req.text.strip() else "(blank)",
            raster=raster,
            height=height,
            width=width_px,
            density=req.density,
            speed=req.speed,
            media=req.media,
        )
    )
    return job.public()


@app.post("/api/print/image")
async def api_print_image(
    request: Request,
    file: UploadFile = File(...),
    label: str = Form("40x30"),
    fit: bool = Form(True),
    threshold: Optional[int] = Form(None),
    density: int = Form(protocol.DEFAULT_DENSITY),
    speed: int = Form(protocol.DEFAULT_SPEED),
    media: int = Form(protocol.DEFAULT_MEDIA),
):
    data = await file.read()
    try:
        width_px, height_px = imaging.label_to_px(label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        img = imaging.Image.open(io.BytesIO(data))
        raster, height, _ = imaging.image_to_raster(
            img, width=width_px, height=height_px if fit else None, threshold=threshold
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Bad image: {exc}")
    job = await _queue(request).add(
        dict(
            type="image",
            label=file.filename or "image",
            raster=raster,
            height=height,
            width=width_px,
            density=density,
            speed=speed,
            media=media,
        )
    )
    return job.public()


@app.get("/api/jobs")
async def api_jobs(request: Request):
    return [j.public() for j in _queue(request).all()]


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: int, request: Request):
    job = _queue(request).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.public()


@app.get("/api/status")
async def api_status(request: Request):
    import os

    q = _queue(request)
    active = next((j for j in q.all() if j.status == "printing"), None)
    return JSONResponse(
        {
            "printer_addr": os.environ.get(printer.ENV_ADDR),
            "pending": q.pending,
            "active_job": active.id if active else None,
            "total_jobs": len(q.all()),
        }
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    import os

    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {"printer_addr": os.environ.get(printer.ENV_ADDR, "(not set)")},
    )
