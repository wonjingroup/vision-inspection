"""
웹캠 + YOLO AI 비전검사 시스템
FastAPI 앱 진입점

Usage:
    python main.py              # 일반 모드
    python main.py --demo       # 데모 모드 (모델 없이 UI 테스트)
    python main.py --port 8080  # 포트 변경
"""
import os
import sys
import argparse
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import (
    BASE_DIR, DATA_DIR, PHOTOS_DIR, MODELS_DIR, DB_PATH,
    DEFAULT_CAMERA_INDEX, DEFAULT_CAMERA_WIDTH, DEFAULT_CAMERA_HEIGHT,
    DEFAULT_CAMERA_FPS, DEFAULT_CONFIDENCE, DEFAULT_IMGSZ,
)
from camera.manager import CameraManager
from ai.detector import YOLODetector
from ai.inspector import InspectionStateMachine
from db.database import Database


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 디렉토리 생성
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # DB 초기화
    db = Database(str(DB_PATH))
    db.init_db()
    db.seed_sp3_products()
    app.state.db = db

    # 설정 로드
    settings = db.get_settings()
    cam_idx = int(settings.get("camera_index", DEFAULT_CAMERA_INDEX))
    cam_w = int(settings.get("camera_width", DEFAULT_CAMERA_WIDTH))
    cam_h = int(settings.get("camera_height", DEFAULT_CAMERA_HEIGHT))
    conf = float(settings.get("confidence_threshold", DEFAULT_CONFIDENCE))
    demo = (settings.get("demo_mode", "0") == "1"
            or os.environ.get("DEMO_MODE", "0") == "1")

    # 카메라 시작
    camera_mgr = CameraManager(cam_idx, cam_w, cam_h, DEFAULT_CAMERA_FPS)
    camera_mgr.start()
    app.state.camera_mgr = camera_mgr

    # YOLO 디텍터
    model_path = None
    active_products = db.get_active_products()
    if active_products:
        mp = active_products[0].get("model_path")
        if mp:
            full = MODELS_DIR / mp
            if full.exists():
                model_path = str(full)

    detector = YOLODetector(
        model_path=model_path,
        conf=conf,
        imgsz=DEFAULT_IMGSZ,
        demo_mode=demo or (model_path is None),
    )
    app.state.detector = detector

    # 검사 상태머신
    inspector = InspectionStateMachine(db, detector=detector)
    app.state.inspector = inspector

    # 추론 쓰레드 시작
    detector.start_inference_thread(camera_mgr.get_frame_with_timestamp)

    # 추론→검사 연결 쓰레드
    _running = True

    def _inspection_loop():
        while _running:
            dets, ts = detector.get_latest_detections()
            ok, frame = camera_mgr.get_frame()
            if ok and frame is not None and ts > 0:
                inspector.update(dets, frame, ts)
            time.sleep(0.03)

    t = threading.Thread(target=_inspection_loop, daemon=True)
    t.start()

    port = getattr(app.state, 'port', 8000)
    print("=" * 50)
    print("  비전검사 시스템 시작")
    print(f"  데모 모드: {'ON' if detector.demo_mode else 'OFF'}")
    print(f"  카메라: #{cam_idx} ({cam_w}x{cam_h})")
    print(f"  브라우저: http://localhost:{port}")
    print("=" * 50)

    yield

    # 종료
    _running = False
    detector.stop()
    camera_mgr.stop()


app = FastAPI(title="비전검사 시스템", lifespan=lifespan)


# 정적 파일 캐시 방지
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheStaticMiddleware)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# API 라우트
from routes.stream import router as stream_router
from routes.products import router as products_router
from routes.inspections import router as inspections_router
from routes.settings import router as settings_router
from routes.training import router as training_router

app.include_router(stream_router, prefix="/api")
app.include_router(products_router, prefix="/api")
app.include_router(inspections_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(training_router, prefix="/api")


# HTML 페이지
@app.get("/")
async def index():
    return FileResponse(str(BASE_DIR / "static" / "index.html"))


@app.get("/products")
async def products_page():
    return FileResponse(str(BASE_DIR / "static" / "products.html"))


@app.get("/stats")
async def stats_page():
    return FileResponse(str(BASE_DIR / "static" / "stats.html"))


@app.get("/training")
async def training_page():
    return FileResponse(str(BASE_DIR / "static" / "training.html"))


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="비전검사 시스템")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--camera", type=int, default=None)
    parser.add_argument("--demo", action="store_true", help="데모 모드")
    args = parser.parse_args()

    if args.demo:
        os.environ["DEMO_MODE"] = "1"
    if args.camera is not None:
        os.environ["CAMERA_INDEX"] = str(args.camera)

    app.state.port = args.port
    uvicorn.run(app, host="0.0.0.0", port=args.port)
