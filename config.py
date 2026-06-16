"""전역 설정 상수."""
from pathlib import Path
import os
import sys

# 경로
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "inspection.db"
PHOTOS_DIR = DATA_DIR / "photos"
MODELS_DIR = BASE_DIR / "models"

# 학습 작업 디렉토리 (한글 경로 우회)
if sys.platform == "win32":
    TRAINING_WORK_DIR = Path("C:/vision")
else:
    TRAINING_WORK_DIR = BASE_DIR / "train_work"

# 카메라 기본값
DEFAULT_CAMERA_INDEX = 0
DEFAULT_CAMERA_WIDTH = 1280
DEFAULT_CAMERA_HEIGHT = 720
DEFAULT_CAMERA_FPS = 30

# 추론
DEFAULT_CONFIDENCE = 0.5
DEFAULT_IOU = 0.45
DEFAULT_IMGSZ = 1280

# 검사 상태머신
PRODUCT_DETECT_FRAMES = 3      # 제품 인식 확정까지 연속 프레임 수
PRODUCT_LOST_FRAMES = 10       # 제품 이탈 확정까지 연속 프레임 수
FACE_SWITCH_FRAMES = 3         # 면 전환 확정까지 연속 프레임 수
PART_COUNT_WINDOW_SEC = 0.5    # 부자재 카운트 롤링 윈도우 (초)
JUDGMENT_HOLD_SEC = 3.0        # OK/NG 결과 표시 유지 시간 (초)

# MJPEG
MJPEG_QUALITY = 80
STREAM_FPS_LIMIT = 25

# 사진
PHOTO_JPEG_QUALITY = 95

# 한글 폰트 (OS별 분기)
if sys.platform == "win32":
    FONT_PATH = "C:/Windows/Fonts/malgun.ttf"
else:
    # Linux/Docker: 나눔고딕 또는 기본 폰트
    _linux_fonts = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    FONT_PATH = next((f for f in _linux_fonts if Path(f).exists()), "")

# 데모 모드
DEMO_MODE = os.environ.get("DEMO_MODE", "0") == "1"
