"""MJPEG 스트리밍 + 검사 상태 API + 브라우저 웹캠 프레임 수신."""
import asyncio
import time
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse

from config import MJPEG_QUALITY, STREAM_FPS_LIMIT, FONT_PATH

router = APIRouter()

# 한글 폰트 캐시
_font_cache: dict[int, ImageFont.FreeTypeFont] = {}


def _get_font(size: int):
    if size not in _font_cache:
        try:
            _font_cache[size] = ImageFont.truetype(FONT_PATH, size)
        except Exception:
            _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]


def draw_text_kr(img: np.ndarray, text: str, pos: tuple,
                 font_size: int = 24, color=(255, 255, 255)) -> np.ndarray:
    """한글 텍스트를 OpenCV 이미지에 렌더링 (Pillow 사용)."""
    pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    font = _get_font(font_size)
    rgb_color = (color[2], color[1], color[0])
    draw.text(pos, text, font=font, fill=rgb_color)
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def draw_overlay(frame: np.ndarray, detections: list, status: dict) -> np.ndarray:
    """검출 박스 + 검사 상태 오버레이."""
    display = frame.copy()
    h, w = display.shape[:2]
    state = status.get("state", "standby")

    # STANDBY: 카메라 피드만 표시, 오버레이 없음
    if state == "standby":
        return display

    # 검출 박스 그리기
    colors = {
        "face_a": (0, 255, 0), "face_b": (255, 165, 0),
        "fastener": (255, 0, 0), "clip": (0, 200, 255),
        "barcode": (255, 255, 0), "protective_wrap": (200, 0, 255),
        "black_pad": (100, 100, 100), "insulate_pad": (0, 150, 200),
    }
    for det in detections:
        color = colors.get(det.class_name, (200, 200, 200))
        x1, y1, x2, y2 = det.bbox
        cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
        label = f"{det.class_name} {det.confidence:.0%}"
        cv2.putText(display, label, (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    # state는 위에서 이미 설정됨

    # 상태 표시 바 (상단)
    cv2.rectangle(display, (0, 0), (w, 40), (30, 30, 30), -1)

    state_labels = {
        "standby": "검사시작 대기",
        "idle": "제품 인식 대기...",
        "detecting": "제품 감지 중...",
        "inspecting_a": "A면 검사 중",
        "inspecting_b": "B면 검사 중",
        "judging": "판정 중...",
        "result_ok": "OK",
        "result_ng": "NG",
    }
    state_text = state_labels.get(state, state)

    product_name = status.get("product_name", "")
    elapsed = status.get("elapsed_sec", 0)
    header = f"[{state_text}]"
    if product_name:
        header += f"  {product_name}"
    if elapsed > 0:
        header += f"  {elapsed:.1f}s"

    display = draw_text_kr(display, header, (10, 8), 22, (255, 255, 255))

    # 부자재 체크리스트 (우측)
    if state in ("inspecting_a", "inspecting_b", "judging",
                 "result_ok", "result_ng"):
        panel_w = 280
        panel_x = w - panel_w - 10
        panel_y = 50

        a_parts = status.get("face_a_parts", {})
        b_parts = status.get("face_b_parts", {})

        y_offset = panel_y
        for face_label, parts in [("A면", a_parts), ("B면", b_parts)]:
            if not parts:
                continue
            cv2.rectangle(display, (panel_x, y_offset),
                          (panel_x + panel_w, y_offset + 28),
                          (50, 50, 50), -1)
            display = draw_text_kr(display, face_label,
                                   (panel_x + 5, y_offset + 3), 20,
                                   (200, 200, 200))
            y_offset += 30

            for ptype, info in parts.items():
                ok = info.get("ok", False)
                bg_color = (0, 80, 0) if ok else (80, 0, 0)
                cv2.rectangle(display, (panel_x, y_offset),
                              (panel_x + panel_w, y_offset + 26),
                              bg_color, -1)
                mark = "O" if ok else "X"
                txt = f" {mark} {info['display_name']} {info['actual']}/{info['required']}"
                color = (0, 255, 0) if ok else (0, 0, 255)
                display = draw_text_kr(display, txt,
                                       (panel_x + 5, y_offset + 2),
                                       18, color)
                y_offset += 28

    return display


@router.get("/stream")
async def mjpeg_stream(request: Request):
    """MJPEG 라이브 스트림 (검출 오버레이 포함)."""
    camera_mgr = request.app.state.camera_mgr
    detector = request.app.state.detector
    inspector = request.app.state.inspector

    async def generate():
        while True:
            if await request.is_disconnected():
                break

            ok, frame = camera_mgr.get_frame()
            if not ok or frame is None:
                await asyncio.sleep(0.04)
                continue

            detections, _ = detector.get_latest_detections()
            status = inspector.get_status()
            display = draw_overlay(frame, detections, status)

            _, jpeg = cv2.imencode(
                ".jpg", display,
                [cv2.IMWRITE_JPEG_QUALITY, MJPEG_QUALITY],
            )
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n"
                   + jpeg.tobytes() + b"\r\n")

            await asyncio.sleep(1.0 / STREAM_FPS_LIMIT)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/status")
async def get_status(request: Request):
    """현재 검사 상태 JSON."""
    inspector = request.app.state.inspector
    return JSONResponse(inspector.get_status())


@router.post("/start")
async def start_inspection(request: Request):
    """검사시작 — STANDBY → IDLE 전환."""
    inspector = request.app.state.inspector
    started = inspector.start_inspection()
    return {"ok": started}


@router.post("/reset")
async def reset_inspection(request: Request):
    """검사 상태 강제 리셋 (→ STANDBY)."""
    inspector = request.app.state.inspector
    inspector.reset()
    return {"ok": True}


@router.post("/frame")
async def receive_frame(request: Request):
    """브라우저 웹캠 프레임 수신 → AI 추론 → 검출 결과 반환."""
    body = await request.body()
    nparr = np.frombuffer(body, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        return JSONResponse({"error": "invalid frame"}, 400)

    camera_mgr = request.app.state.camera_mgr
    detector = request.app.state.detector
    inspector = request.app.state.inspector

    # 프레임을 카메라 매니저에 주입 (기존 파이프라인과 통합)
    camera_mgr.inject_frame(frame)

    # 직접 추론 실행 (paused 상태가 아닐 때만)
    detections = []
    if not detector._paused:
        detections = detector.detect(frame)
        inspector.update(detections, frame, time.time())

    status = inspector.get_status()
    det_list = [{
        "class_name": d.class_name,
        "confidence": d.confidence,
        "bbox": list(d.bbox),
    } for d in detections]

    return {"detections": det_list, "status": status}
