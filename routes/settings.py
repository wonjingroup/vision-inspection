"""설정 API."""
from fastapi import APIRouter, Request
from db.models import SettingsUpdate

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def get_settings(request: Request):
    return request.app.state.db.get_settings()


@router.put("/settings")
async def update_settings(request: Request, body: SettingsUpdate):
    db = request.app.state.db
    camera_mgr = request.app.state.camera_mgr
    detector = request.app.state.detector
    fields = body.model_dump(exclude_unset=True)

    for k, v in fields.items():
        db.set_setting(k, str(v))

    # 카메라 변경 시 재시작
    if "camera_index" in fields:
        camera_mgr.switch_camera(
            int(fields["camera_index"]),
            int(fields.get("camera_width", 1280)),
            int(fields.get("camera_height", 720)),
        )

    # 데모 모드 토글
    if "demo_mode" in fields:
        detector.demo_mode = fields["demo_mode"]

    # 신뢰도 변경
    if "confidence_threshold" in fields:
        detector._conf = float(fields["confidence_threshold"])

    return {"ok": True}


@router.get("/cameras")
async def list_cameras():
    from camera.manager import CameraManager
    return CameraManager.list_cameras()
