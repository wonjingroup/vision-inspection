"""검사 상태머신 — 부자재 카운트 + OK/NG 판정."""
import enum
import time
import copy
import threading
import cv2
import numpy as np
from collections import deque
from datetime import datetime
from pathlib import Path

from ai.detector import Detection
from config import (
    PRODUCT_DETECT_FRAMES, PRODUCT_LOST_FRAMES, FACE_SWITCH_FRAMES,
    PART_COUNT_WINDOW_SEC, JUDGMENT_HOLD_SEC,
    PHOTOS_DIR, PHOTO_JPEG_QUALITY,
)


class InspectionState(enum.Enum):
    STANDBY = "standby"        # 검사시작 버튼 대기
    IDLE = "idle"              # 제품 인식 대기 (검사시작 클릭 후)
    DETECTING = "detecting"
    INSPECTING_A = "inspecting_a"
    INSPECTING_B = "inspecting_b"
    JUDGING = "judging"
    RESULT_OK = "result_ok"
    RESULT_NG = "result_ng"


class InspectionStateMachine:
    """
    검사 로직 핵심.

    wonjin-qa 패턴 적용:
    - "부재=NG": 검출 카운트 < 기준 → NG
    - 롤링 맥스 윈도우: 순간 가림을 보정
    - 히스테리시스: 상태 전환에 N프레임 연속 확인
    """

    def __init__(self, db, detector=None):
        self._db = db
        self._detector = detector
        self._lock = threading.Lock()

        self.state = InspectionState.STANDBY
        self._active_product: dict | None = None
        self._parts_a: list[dict] = []
        self._parts_b: list[dict] = []

        # 카운트 롤링 윈도우: {part_type: deque of (timestamp, count)}
        self._count_window_a: dict[str, deque] = {}
        self._count_window_b: dict[str, deque] = {}

        # 히스테리시스 카운터
        self._detect_counter = 0
        self._lost_counter = 0
        self._face_switch_counter = 0
        self._pending_face: str | None = None

        # 최고 프레임 저장 (사진 용도)
        self._best_frame_a: np.ndarray | None = None
        self._best_frame_b: np.ndarray | None = None
        self._best_score_a: int = 0
        self._best_score_b: int = 0

        # 검사 시작 시각
        self._inspection_start: float = 0
        # 결과 표시 시작 시각
        self._result_start: float = 0

        # 현재 면
        self._current_face: str = "A"

        # 마지막 판정 결과 (UI 참조용)
        self._last_result: str | None = None
        self._last_missing: list[dict] = []

    # ── 메인 업데이트 ───────────────────────────────────────

    def update(self, detections: list[Detection], frame: np.ndarray,
               timestamp: float):
        with self._lock:
            self._update_internal(detections, frame, timestamp)

    def _update_internal(self, detections: list[Detection],
                         frame: np.ndarray, timestamp: float):
        if self.state == InspectionState.STANDBY:
            return  # 검사시작 버튼 대기 — 아무것도 하지 않음
        elif self.state == InspectionState.IDLE:
            self._handle_idle(detections, timestamp)
        elif self.state == InspectionState.DETECTING:
            self._handle_detecting(detections, timestamp)
        elif self.state == InspectionState.INSPECTING_A:
            self._handle_inspecting(detections, frame, timestamp, "A")
        elif self.state == InspectionState.INSPECTING_B:
            self._handle_inspecting(detections, frame, timestamp, "B")
        elif self.state == InspectionState.JUDGING:
            self._handle_judging()
        elif self.state in (InspectionState.RESULT_OK, InspectionState.RESULT_NG):
            self._handle_result(detections, timestamp)

    # ── 상태 핸들러 ─────────────────────────────────────────

    def _handle_idle(self, detections, timestamp):
        face = self._detect_face(detections)
        if face:
            self._detect_counter += 1
            self._pending_face = face
            if self._detect_counter >= PRODUCT_DETECT_FRAMES:
                self.state = InspectionState.DETECTING
                self._detect_counter = 0
        else:
            self._detect_counter = 0
            self._pending_face = None

    def _handle_detecting(self, detections, timestamp):
        # 활성 제품 로드
        products = self._db.get_active_products()
        if not products:
            self.state = InspectionState.IDLE
            return

        # 제품 식별: face 클래스명으로 매칭
        face_detected = self._detect_face(detections)
        if not face_detected:
            self._detect_counter += 1
            if self._detect_counter > PRODUCT_LOST_FRAMES:
                self.state = InspectionState.IDLE
                self._detect_counter = 0
            return

        self._detect_counter = 0
        product = self._identify_product(detections, products)
        if product is None:
            # 제품 특정 실패 시 첫 번째 활성 제품 사용
            product = products[0]

        self._active_product = product
        self._parts_a = self._db.get_product_parts_by_face(product["id"], "A")
        self._parts_b = self._db.get_product_parts_by_face(product["id"], "B")

        # 카운트 윈도우 초기화
        self._count_window_a = {p["yolo_class_name"]: deque() for p in self._parts_a}
        self._count_window_b = {p["yolo_class_name"]: deque() for p in self._parts_b}

        # 최고 프레임 리셋
        self._best_frame_a = None
        self._best_frame_b = None
        self._best_score_a = 0
        self._best_score_b = 0

        self._inspection_start = time.time()
        self._lost_counter = 0
        self._face_switch_counter = 0

        # 시작 면 결정
        if face_detected == "A":
            self.state = InspectionState.INSPECTING_A
            self._current_face = "A"
        else:
            self.state = InspectionState.INSPECTING_B
            self._current_face = "B"

    def _handle_inspecting(self, detections, frame, timestamp, face: str):
        parts = self._parts_a if face == "A" else self._parts_b
        count_window = self._count_window_a if face == "A" else self._count_window_b

        # 면 감지 체크
        face_det = self._detect_face(detections)

        # 부자재 카운트
        counts = self._count_parts(detections, parts)
        for cls_name, cnt in counts.items():
            if cls_name in count_window:
                count_window[cls_name].append((timestamp, cnt))
                # 오래된 항목 제거
                while (count_window[cls_name] and
                       timestamp - count_window[cls_name][0][0] > PART_COUNT_WINDOW_SEC):
                    count_window[cls_name].popleft()

        # 최고 프레임 갱신
        total_score = sum(counts.values())
        if face == "A" and total_score > self._best_score_a:
            self._best_score_a = total_score
            self._best_frame_a = frame.copy()
        elif face == "B" and total_score > self._best_score_b:
            self._best_score_b = total_score
            self._best_frame_b = frame.copy()

        # 면 전환 감지
        other_face = "B" if face == "A" else "A"
        if face_det == other_face:
            self._face_switch_counter += 1
            if self._face_switch_counter >= FACE_SWITCH_FRAMES:
                if face == "A":
                    self.state = InspectionState.INSPECTING_B
                    self._current_face = "B"
                else:
                    self.state = InspectionState.INSPECTING_A
                    self._current_face = "A"
                self._face_switch_counter = 0
                self._lost_counter = 0
                return
        else:
            self._face_switch_counter = 0

        # 제품 이탈 감지
        if face_det is None:
            self._lost_counter += 1
            if self._lost_counter >= PRODUCT_LOST_FRAMES:
                self.state = InspectionState.JUDGING
                self._lost_counter = 0
        else:
            self._lost_counter = 0

    def _handle_judging(self):
        missing = []
        # A면 체크
        for part in self._parts_a:
            max_count = self._get_max_count(
                self._count_window_a.get(part["yolo_class_name"], deque())
            )
            if max_count < part["required_count"]:
                missing.append({
                    "part_type": part["part_type"],
                    "display_name": part["display_name"],
                    "face": "A",
                    "required": part["required_count"],
                    "actual": max_count,
                })
        # B면 체크
        for part in self._parts_b:
            max_count = self._get_max_count(
                self._count_window_b.get(part["yolo_class_name"], deque())
            )
            if max_count < part["required_count"]:
                missing.append({
                    "part_type": part["part_type"],
                    "display_name": part["display_name"],
                    "face": "B",
                    "required": part["required_count"],
                    "actual": max_count,
                })

        result = "OK" if not missing else "NG"
        self._last_result = result
        self._last_missing = missing
        self._result_start = time.time()

        # DB 저장
        if self._active_product:
            a_photo = None
            b_photo = None
            if result == "OK":
                a_photo = self._save_photo("A", self._best_frame_a)
                b_photo = self._save_photo("B", self._best_frame_b)

            self._db.save_inspection(
                product_id=self._active_product["id"],
                product_name=self._active_product["name"],
                result=result,
                missing_parts=missing if missing else None,
                a_face_photo=a_photo,
                b_face_photo=b_photo,
                duration_sec=time.time() - self._inspection_start,
            )

        self.state = (InspectionState.RESULT_OK if result == "OK"
                      else InspectionState.RESULT_NG)

    def _handle_result(self, detections, timestamp):
        elapsed = time.time() - self._result_start
        if elapsed >= JUDGMENT_HOLD_SEC:
            # 결과 표시 종료 조건: 시간 초과 + 제품 없음
            face = self._detect_face(detections)
            if face is None or elapsed >= JUDGMENT_HOLD_SEC * 3:
                self._reset()

    # ── 유틸리티 ────────────────────────────────────────────

    def _detect_face(self, detections: list[Detection]) -> str | None:
        for d in detections:
            if d.class_name == "face_a":
                return "A"
            if d.class_name == "face_b":
                return "B"
            # 제품별 커스텀 face 클래스 체크
            if self._active_product:
                if d.class_name == self._active_product.get("face_a_class"):
                    return "A"
                if d.class_name == self._active_product.get("face_b_class"):
                    return "B"
        return None

    def _identify_product(self, detections: list[Detection],
                          products: list[dict]) -> dict | None:
        for d in detections:
            for p in products:
                if (d.class_name == p.get("face_a_class") or
                        d.class_name == p.get("face_b_class")):
                    return p
        return None

    def _count_parts(self, detections: list[Detection],
                     parts: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for part in parts:
            cls = part["yolo_class_name"]
            counts[cls] = sum(
                1 for d in detections
                if d.class_name == cls and d.confidence >= part["confidence_threshold"]
            )
        return counts

    @staticmethod
    def _get_max_count(window: deque) -> int:
        if not window:
            return 0
        return max(cnt for _, cnt in window)

    def _save_photo(self, face: str, frame: np.ndarray | None) -> str | None:
        if frame is None:
            return None
        today = datetime.now().strftime("%Y-%m-%d")
        date_dir = PHOTOS_DIR / today
        date_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S_%f")
        fname = f"{face}_{ts}.jpg"
        fpath = date_dir / fname
        cv2.imwrite(str(fpath), frame,
                    [cv2.IMWRITE_JPEG_QUALITY, PHOTO_JPEG_QUALITY])
        return f"{today}/{fname}"

    def _reset(self):
        self.state = InspectionState.STANDBY
        if self._detector:
            self._detector.pause()
        self._active_product = None
        self._parts_a = []
        self._parts_b = []
        self._count_window_a = {}
        self._count_window_b = {}
        self._detect_counter = 0
        self._lost_counter = 0
        self._face_switch_counter = 0
        self._pending_face = None
        self._best_frame_a = None
        self._best_frame_b = None
        self._best_score_a = 0
        self._best_score_b = 0
        self._current_face = "A"

    def reset(self):
        with self._lock:
            self._reset()

    def start_inspection(self):
        """검사시작 — STANDBY → IDLE 전환 (제품 인식 대기)."""
        with self._lock:
            if self.state == InspectionState.STANDBY:
                self.state = InspectionState.IDLE
                if self._detector:
                    self._detector.resume()
                return True
            return False

    # ── 상태 조회 (쓰레드 안전) ─────────────────────────────

    def get_status(self) -> dict:
        with self._lock:
            status = {
                "state": self.state.value,
                "current_face": self._current_face,
                "product_name": None,
                "product_code": None,
                "face_a_parts": {},
                "face_b_parts": {},
                "result": self._last_result,
                "missing_parts": copy.deepcopy(self._last_missing),
                "elapsed_sec": 0,
            }

            if self._active_product:
                status["product_name"] = self._active_product["name"]
                status["product_code"] = self._active_product.get("code", "")

            if self.state not in (InspectionState.IDLE, InspectionState.DETECTING):
                status["elapsed_sec"] = round(
                    time.time() - self._inspection_start, 1
                )

            # A면 부자재 상태
            for part in self._parts_a:
                cls = part["yolo_class_name"]
                max_cnt = self._get_max_count(
                    self._count_window_a.get(cls, deque())
                )
                status["face_a_parts"][part["part_type"]] = {
                    "display_name": part["display_name"],
                    "required": part["required_count"],
                    "actual": max_cnt,
                    "ok": max_cnt >= part["required_count"],
                }

            # B면 부자재 상태
            for part in self._parts_b:
                cls = part["yolo_class_name"]
                max_cnt = self._get_max_count(
                    self._count_window_b.get(cls, deque())
                )
                status["face_b_parts"][part["part_type"]] = {
                    "display_name": part["display_name"],
                    "required": part["required_count"],
                    "actual": max_cnt,
                    "ok": max_cnt >= part["required_count"],
                }

            return status
