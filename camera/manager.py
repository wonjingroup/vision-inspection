"""웹캠 캡처 쓰레드 — 디커플드 캡처 패턴."""
import os
import sys
import threading
import time
import cv2
import numpy as np


class CameraManager:
    """
    별도 데몬 쓰레드에서 웹캠 프레임을 캡처.
    소비자는 get_frame()으로 최신 프레임을 non-blocking 읽기.
    카메라 없는 환경(클라우드)에서는 합성 프레임 자동 생성.
    """

    def __init__(self, camera_index: int = 0,
                 width: int = 1280, height: int = 720, fps: int = 30):
        self._camera_index = camera_index
        self._width = width
        self._height = height
        self._fps = fps

        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._no_camera = False  # 카메라 없는 환경 플래그

        self._lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._frame_time: float = 0.0
        self._frame_count: int = 0

    # ── 공개 API ────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._open_camera()
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        if self._cap:
            self._cap.release()
            self._cap = None

    def get_frame(self) -> tuple[bool, np.ndarray | None]:
        with self._lock:
            if self._latest_frame is None:
                return False, None
            return True, self._latest_frame.copy()

    def get_frame_with_timestamp(self) -> tuple[bool, np.ndarray | None, float]:
        with self._lock:
            if self._latest_frame is None:
                return False, None, 0.0
            return True, self._latest_frame.copy(), self._frame_time

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def is_running(self) -> bool:
        return self._running

    def switch_camera(self, camera_index: int, width: int = None,
                      height: int = None):
        self.stop()
        self._camera_index = camera_index
        if width:
            self._width = width
        if height:
            self._height = height
        self.start()

    @staticmethod
    def list_cameras(max_check: int = 10) -> list[dict]:
        cameras = []
        for i in range(max_check):
            if sys.platform == "win32":
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(i)
            if cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cameras.append({"index": i, "width": w, "height": h})
                cap.release()
        return cameras

    # ── 내부 ────────────────────────────────────────────────

    def _open_camera(self) -> bool:
        """카메라 열기. 성공 시 True, 실패 시 False."""
        # Windows: DirectShow 우선 시도
        if sys.platform == "win32":
            self._cap = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)
            if not self._cap.isOpened():
                self._cap = cv2.VideoCapture(self._camera_index)
        else:
            self._cap = cv2.VideoCapture(self._camera_index)

        if not self._cap.isOpened():
            return False

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return True

    def _generate_synthetic_frame(self) -> np.ndarray:
        """카메라 없는 환경용 합성 프레임 생성."""
        frame = np.zeros((self._height, self._width, 3), dtype=np.uint8)
        frame[:] = (40, 40, 40)  # 어두운 회색 배경
        cv2.putText(frame, "DEMO MODE - No Camera",
                    (self._width // 2 - 200, self._height // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (100, 100, 100), 2)
        return frame

    def _capture_loop(self):
        fail_count = 0
        open_attempts = 0
        while self._running:
            # 카메라 없는 환경: 합성 프레임
            if self._no_camera:
                frame = self._generate_synthetic_frame()
                with self._lock:
                    self._latest_frame = frame
                    self._frame_time = time.time()
                    self._frame_count += 1
                time.sleep(1.0 / self._fps)
                continue

            if self._cap is None or not self._cap.isOpened():
                open_attempts += 1
                if open_attempts > 3:
                    # 3회 이상 실패 → 카메라 없는 환경으로 전환
                    print("[Camera] 카메라를 찾을 수 없습니다. 합성 프레임 모드로 전환.")
                    self._no_camera = True
                    continue
                time.sleep(1)
                self._open_camera()
                continue

            open_attempts = 0
            ret, frame = self._cap.read()
            if not ret:
                fail_count += 1
                if fail_count > 150:  # ~5초 (30fps)
                    self._cap.release()
                    time.sleep(1)
                    self._open_camera()
                    fail_count = 0
                continue

            fail_count = 0
            with self._lock:
                self._latest_frame = frame
                self._frame_time = time.time()
                self._frame_count += 1
