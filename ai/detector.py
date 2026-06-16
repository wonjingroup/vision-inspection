"""YOLO 추론 엔진 + 데모 모드."""
import threading
import time
import math
import numpy as np
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Detection:
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    class_id: int = 0


class YOLODetector:
    """
    Ultralytics YOLO 래핑.
    별도 쓰레드에서 추론 실행, 최신 결과를 공유.
    모델 미로드 시 데모 모드로 동작.
    """

    def __init__(self, model_path: str | None = None,
                 conf: float = 0.5, imgsz: int = 640,
                 demo_mode: bool = False):
        self._model = None
        self._conf = conf
        self._imgsz = imgsz
        self._demo_mode = demo_mode
        self._model_path = model_path

        self._lock = threading.Lock()
        self._latest_detections: list[Detection] = []
        self._det_timestamp: float = 0.0

        self._thread: threading.Thread | None = None
        self._running = False

        self._demo_start = time.time()
        self._paused = True  # STANDBY 상태에서 추론 중지

        if model_path:
            self.load_model(model_path)

    def load_model(self, model_path: str) -> bool:
        try:
            from ultralytics import YOLO
            self._model = YOLO(model_path)
            self._model_path = model_path
            self._demo_mode = False
            return True
        except Exception as e:
            print(f"[Detector] 모델 로드 실패: {e}")
            self._model = None
            return False

    @property
    def demo_mode(self) -> bool:
        return self._demo_mode

    @demo_mode.setter
    def demo_mode(self, val: bool):
        self._demo_mode = val
        self._demo_start = time.time()

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if self._demo_mode or self._model is None:
            return self._generate_mock_detections(frame)

        results = self._model.predict(
            frame, conf=self._conf, iou=0.45,
            imgsz=self._imgsz, verbose=False
        )
        detections = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                cls_id = int(box.cls[0])
                cls_name = r.names[cls_id]
                conf = float(box.conf[0])
                detections.append(Detection(
                    class_name=cls_name,
                    confidence=conf,
                    bbox=(int(x1), int(y1), int(x2), int(y2)),
                    class_id=cls_id,
                ))
        return detections

    # ── 추론 쓰레드 ─────────────────────────────────────────

    def start_inference_thread(self, frame_source: Callable):
        if self._running:
            return
        self._running = True
        self._frame_source = frame_source
        self._thread = threading.Thread(
            target=self._inference_loop, daemon=True
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def get_latest_detections(self) -> tuple[list[Detection], float]:
        with self._lock:
            return list(self._latest_detections), self._det_timestamp

    def pause(self):
        """추론 일시정지 (STANDBY)."""
        self._paused = True
        with self._lock:
            self._latest_detections = []
            self._det_timestamp = 0.0

    def resume(self):
        """추론 재개 (검사시작)."""
        self._paused = False

    def _inference_loop(self):
        last_ts = 0.0
        while self._running:
            if self._paused:
                time.sleep(0.05)
                continue

            ok, frame, ts = self._frame_source()
            if not ok or frame is None:
                time.sleep(0.03)
                continue
            # 같은 프레임이면 스킵
            if ts == last_ts and not self._demo_mode:
                time.sleep(0.01)
                continue
            last_ts = ts

            detections = self.detect(frame)
            with self._lock:
                self._latest_detections = detections
                self._det_timestamp = time.time()

    # ── 데모 모드 ───────────────────────────────────────────

    def _generate_mock_detections(self, frame: np.ndarray) -> list[Detection]:
        """
        15초 주기로 검사 사이클 시뮬레이션:
         0-2초: 비어있음 (IDLE)
         2-6초: face_a + A면 부자재
         6-8초: 전환 (비어있음)
         8-12초: face_b + B면 부자재
         12-14초: 비어있음 → 판정
         14-15초: 리셋
        """
        h, w = frame.shape[:2]
        elapsed = (time.time() - self._demo_start) % 15.0
        dets = []

        cx, cy = w // 2, h // 2

        if 2.0 <= elapsed < 6.0:
            # A면 인식 + 부자재들
            dets.append(Detection("face_a", 0.92,
                                  (cx - 200, cy - 150, cx + 200, cy + 150)))
            dets.append(Detection("fastener", 0.88,
                                  (cx - 160, cy - 100, cx - 120, cy - 60)))
            dets.append(Detection("fastener", 0.85,
                                  (cx + 120, cy - 100, cx + 160, cy - 60)))
            dets.append(Detection("clip", 0.90,
                                  (cx - 50, cy + 80, cx - 10, cy + 120)))
            dets.append(Detection("clip", 0.87,
                                  (cx + 10, cy + 80, cx + 50, cy + 120)))
            dets.append(Detection("barcode", 0.95,
                                  (cx + 100, cy - 30, cx + 180, cy + 10)))
            dets.append(Detection("protective_wrap", 0.82,
                                  (cx - 180, cy + 40, cx - 100, cy + 100)))
        elif 8.0 <= elapsed < 12.0:
            # B면 인식 + 부자재들
            dets.append(Detection("face_b", 0.91,
                                  (cx - 200, cy - 150, cx + 200, cy + 150)))
            dets.append(Detection("black_pad", 0.89,
                                  (cx - 80, cy - 60, cx - 20, cy)))
            dets.append(Detection("black_pad", 0.86,
                                  (cx + 20, cy - 60, cx + 80, cy)))
            dets.append(Detection("insulate_pad", 0.84,
                                  (cx - 50, cy + 30, cx + 50, cy + 90)))
            dets.append(Detection("fastener", 0.88,
                                  (cx - 160, cy - 100, cx - 120, cy - 60)))

        return dets
