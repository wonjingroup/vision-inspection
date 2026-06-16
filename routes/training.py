"""데이터 수집 + 라벨링 + YOLO 학습 API (제품별 데이터셋)."""
import json
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from config import BASE_DIR, MODELS_DIR, TRAINING_WORK_DIR

router = APIRouter(tags=["training"])

DATASET_DIR = BASE_DIR / "dataset"
COMMON_DIR = DATASET_DIR / "common"  # 공용 이미지 디렉토리

# 학습 상태 (전역)
_training_state = {
    "running": False,
    "progress": 0,
    "epoch": 0,
    "total_epochs": 0,
    "status": "idle",
    "message": "",
    "model_path": None,
}
_training_lock = threading.Lock()


def _product_dir(product_code: str) -> Path:
    """제품별 데이터셋 경로."""
    safe = product_code.replace("/", "_").replace("\\", "_")
    return DATASET_DIR / safe


# ── 프레임 캡처 ────────────────────────────────────────────

@router.post("/training/capture")
async def capture_frame(request: Request, product_code: str = "default"):
    """현재 카메라 프레임을 캡처하여 제품별 폴더에 저장."""
    camera_mgr = request.app.state.camera_mgr
    ok, frame = camera_mgr.get_frame()
    if not ok or frame is None:
        return JSONResponse({"error": "카메라 프레임 없음"}, 400)

    img_dir = _product_dir(product_code) / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"cap_{ts}.jpg"
    filepath = img_dir / filename
    # 한글 경로 대응: cv2.imwrite 대신 imencode + write_bytes 사용
    success, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not success:
        return JSONResponse({"error": "이미지 인코딩 실패"}, 500)
    filepath.write_bytes(buf.tobytes())

    h, w = frame.shape[:2]
    return {
        "filename": filename,
        "width": w,
        "height": h,
        "url": f"/api/training/images/{product_code}/{filename}",
    }


@router.get("/training/images/{product_code}/{filename}")
async def get_image(product_code: str, filename: str):
    filepath = _product_dir(product_code) / "images" / filename
    if not filepath.exists():
        return JSONResponse({"error": "이미지 없음"}, 404)
    return FileResponse(str(filepath), media_type="image/jpeg")


@router.get("/training/images")
async def list_images(product_code: str = "default"):
    """제품별 수집 이미지 + 공용 이미지 목록."""
    # 공용 + 제품 클래스 병합
    class_names = _merged_classes(product_code)

    images = []

    # 1) 공용 이미지 (common) — product_code가 common이 아닌 경우만
    if product_code != "common":
        common_img_dir = COMMON_DIR / "images"
        common_lbl_dir = COMMON_DIR / "labels"
        common_img_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(common_img_dir.glob("*.jpg")):
            label_file = common_lbl_dir / f"{f.stem}.txt"
            has_label = label_file.exists() and label_file.read_text().strip()
            label_count = 0
            label_classes = []
            if has_label:
                for line in label_file.read_text().strip().split("\n"):
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        label_count += 1
                        cid = int(parts[0])
                        if cid < len(class_names):
                            label_classes.append(class_names[cid])
            images.append({
                "filename": f.name,
                "url": f"/api/training/images/common/{f.name}",
                "has_label": bool(has_label),
                "label_count": label_count,
                "label_classes": label_classes,
                "source": "common",
            })

    # 2) 제품별 이미지
    img_dir = _product_dir(product_code) / "images"
    lbl_dir = _product_dir(product_code) / "labels"
    img_dir.mkdir(parents=True, exist_ok=True)
    for f in sorted(img_dir.glob("*.jpg")):
        label_file = lbl_dir / f"{f.stem}.txt"
        has_label = label_file.exists() and label_file.read_text().strip()
        label_count = 0
        label_classes = []
        if has_label:
            for line in label_file.read_text().strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 5:
                    label_count += 1
                    cid = int(parts[0])
                    if cid < len(class_names):
                        label_classes.append(class_names[cid])
        images.append({
            "filename": f.name,
            "url": f"/api/training/images/{product_code}/{f.name}",
            "has_label": bool(has_label),
            "label_count": label_count,
            "label_classes": label_classes,
            "source": "product",
        })
    return images


@router.delete("/training/images/{product_code}/{filename}")
async def delete_image(product_code: str, filename: str):
    pdir = _product_dir(product_code)
    stem = Path(filename).stem
    img = pdir / "images" / filename
    lbl_txt = pdir / "labels" / f"{stem}.txt"
    lbl_json = pdir / "labels" / f"{stem}.json"
    if img.exists():
        img.unlink()
    if lbl_txt.exists():
        lbl_txt.unlink()
    if lbl_json.exists():
        lbl_json.unlink()
    return {"ok": True}


# ── 라벨 저장/조회 ─────────────────────────────────────────

@router.post("/training/labels/{product_code}/{filename}")
async def save_labels(product_code: str, filename: str, request: Request):
    """라벨 저장 — JSON(원본) + YOLO txt(학습용) 동시 생성."""
    pdir = _product_dir(product_code)
    lbl_dir = pdir / "labels"
    lbl_dir.mkdir(parents=True, exist_ok=True)

    body = await request.json()
    labels = body.get("labels", [])
    class_names = body.get("class_names", [])

    stem = Path(filename).stem

    # 1) JSON 원본 저장 (shape 정보 포함)
    json_path = lbl_dir / f"{stem}.json"
    json_path.write_text(json.dumps({
        "labels": labels, "class_names": class_names,
    }, ensure_ascii=False), encoding="utf-8")

    # 2) YOLO txt 생성 (바운딩박스 — 학습용)
    txt_path = lbl_dir / f"{stem}.txt"
    lines = []
    for lbl in labels:
        cls_name = lbl.get("class_name", "")
        if cls_name in class_names:
            cls_id = class_names.index(cls_name)
        else:
            class_names.append(cls_name)
            cls_id = len(class_names) - 1

        bbox = _label_to_bbox(lbl)
        lines.append(f"{cls_id} {bbox[0]:.6f} {bbox[1]:.6f} {bbox[2]:.6f} {bbox[3]:.6f}")

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    # 클래스 목록 저장
    classes_path = pdir / "classes.txt"
    classes_path.write_text("\n".join(class_names), encoding="utf-8")

    return {"ok": True, "count": len(lines), "class_names": class_names}


def _label_to_bbox(lbl: dict) -> tuple[float, float, float, float]:
    """shape별 라벨 → YOLO bbox (cx, cy, w, h) 변환."""
    shape = lbl.get("shape", "box")
    if shape == "box":
        return (lbl["cx"], lbl["cy"], lbl["w"], lbl["h"])
    elif shape == "circle":
        r = lbl["r"]
        return (lbl["cx"], lbl["cy"], r * 2, r * 2)
    elif shape == "freeform" and lbl.get("points"):
        xs = [p["x"] for p in lbl["points"]]
        ys = [p["y"] for p in lbl["points"]]
        x1, x2 = min(xs), max(xs)
        y1, y2 = min(ys), max(ys)
        return ((x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1)
    return (0.5, 0.5, 0.1, 0.1)


@router.get("/training/labels/{product_code}/{filename}")
async def get_labels(product_code: str, filename: str):
    pdir = _product_dir(product_code)
    classes_path = pdir / "classes.txt"
    class_names = _load_classes(classes_path)
    stem = Path(filename).stem

    # JSON 우선 로드 (shape 정보 포함)
    json_path = pdir / "labels" / f"{stem}.json"
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return {"labels": data.get("labels", []), "class_names": data.get("class_names", class_names)}

    # 없으면 YOLO txt 폴백 (box만)
    txt_path = pdir / "labels" / f"{stem}.txt"
    labels = []
    if txt_path.exists():
        for line in txt_path.read_text().strip().split("\n"):
            if not line.strip():
                continue
            parts = line.strip().split()
            cls_id = int(parts[0])
            cx, cy, w, h = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            cls_name = class_names[cls_id] if cls_id < len(class_names) else f"class_{cls_id}"
            labels.append({
                "class_id": cls_id, "class_name": cls_name,
                "shape": "box", "cx": cx, "cy": cy, "w": w, "h": h,
            })

    return {"labels": labels, "class_names": class_names}


# ── 클래스 관리 ─────────────────────────────────────────

@router.get("/training/classes")
async def get_classes(product_code: str = "default"):
    return {"class_names": _merged_classes(product_code)}


@router.post("/training/classes")
async def save_classes(request: Request, product_code: str = "default"):
    pdir = _product_dir(product_code)
    pdir.mkdir(parents=True, exist_ok=True)
    body = await request.json()
    names = body.get("class_names", [])
    classes_path = pdir / "classes.txt"
    classes_path.write_text("\n".join(names), encoding="utf-8")
    return {"ok": True}


# ── 데이터셋 통계 ──────────────────────────────────────────

@router.get("/training/stats")
async def dataset_stats(product_code: str = "default"):
    class_names = _merged_classes(product_code)
    total_images = 0
    labeled_images = 0
    class_counts = {name: 0 for name in class_names}

    # 공용 + 제품별 디렉토리 순회
    dirs = []
    if product_code != "common":
        dirs.append(COMMON_DIR)
    dirs.append(_product_dir(product_code))

    for pdir in dirs:
        img_dir = pdir / "images"
        lbl_dir = pdir / "labels"
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)

        total_images += len(list(img_dir.glob("*.jpg")))
        for lbl_file in lbl_dir.glob("*.txt"):
            content = lbl_file.read_text().strip()
            if not content:
                continue
            labeled_images += 1
            for line in content.split("\n"):
                parts = line.strip().split()
                if len(parts) >= 5:
                    cls_id = int(parts[0])
                    if cls_id < len(class_names):
                        class_counts[class_names[cls_id]] = class_counts.get(class_names[cls_id], 0) + 1

    return {
        "total_images": total_images,
        "labeled_images": labeled_images,
        "unlabeled_images": total_images - labeled_images,
        "class_names": class_names,
        "class_counts": class_counts,
    }


# ── YOLO 학습 ──────────────────────────────────────────────

@router.post("/training/start")
async def start_training(request: Request):
    with _training_lock:
        if _training_state["running"]:
            return JSONResponse({"error": "이미 학습 중입니다"}, 400)

    body = await request.json()
    product_code = body.get("product_code", "default")
    epochs = body.get("epochs", 100)
    imgsz = body.get("imgsz", 640)
    batch = body.get("batch", 8)

    # 공용 + 제품별 라벨링 이미지 수 확인
    total_labeled = 0
    for d in [COMMON_DIR, _product_dir(product_code)]:
        img_d = d / "images"
        lbl_d = d / "labels"
        if img_d.exists():
            total_labeled += sum(
                1 for f in img_d.glob("*.jpg")
                if (lbl_d / f"{f.stem}.txt").exists()
                and (lbl_d / f"{f.stem}.txt").read_text().strip()
            )
    if total_labeled < 1:
        return JSONResponse(
            {"error": "라벨링된 이미지가 없습니다. 최소 1개 이상 필요합니다."},
            status_code=400,
        )

    t = threading.Thread(
        target=_run_training,
        args=(request.app, product_code, epochs, imgsz, batch),
        daemon=True,
    )
    t.start()
    return {"ok": True, "message": "학습 시작됨"}


@router.get("/training/status")
async def training_status():
    with _training_lock:
        return dict(_training_state)


def _run_training(app, product_code: str, epochs: int, imgsz: int, batch: int):
    global _training_state
    _update_state(running=True, progress=0, epoch=0, total_epochs=epochs,
                  status="preparing", message="데이터셋 준비 중...", model_path=None)

    try:
        pdir = _product_dir(product_code)
        class_names = _merged_classes(product_code)

        # 한글 경로 우회
        safe_code = product_code.replace("-", "").replace(" ", "_")[:20]
        work_dir = TRAINING_WORK_DIR / safe_code
        train_img = work_dir / "images" / "train"
        val_img = work_dir / "images" / "val"
        train_lbl = work_dir / "labels" / "train"
        val_lbl = work_dir / "labels" / "val"

        for d in [train_img, val_img, train_lbl, val_lbl]:
            d.mkdir(parents=True, exist_ok=True)
            for f in d.glob("*"):
                f.unlink()

        # 공용 + 제품별 라벨링 이미지 수집
        labeled = []
        for src_dir in [COMMON_DIR, pdir]:
            img_dir = src_dir / "images"
            lbl_dir = src_dir / "labels"
            if not img_dir.exists():
                continue
            for f in sorted(img_dir.glob("*.jpg")):
                lbl = lbl_dir / f"{f.stem}.txt"
                if lbl.exists() and lbl.read_text().strip():
                    labeled.append((f, lbl))

        # temporal split (소량 데이터 대응: 3장 이하면 전부 train=val로 공유)
        if len(labeled) <= 3:
            train_set = labeled
            val_set = labeled  # 동일 데이터로 검증
        else:
            split_idx = max(1, int(len(labeled) * 0.8))
            train_set = labeled[:split_idx]
            val_set = labeled[split_idx:] if split_idx < len(labeled) else labeled[-1:]

        _update_state(message=f"학습:{len(train_set)}장, 검증:{len(val_set)}장 복사 중...")

        for img_f, lbl_f in train_set:
            shutil.copy2(img_f, train_img / img_f.name)
            shutil.copy2(lbl_f, train_lbl / lbl_f.name)
        for img_f, lbl_f in val_set:
            shutil.copy2(img_f, val_img / img_f.name)
            shutil.copy2(lbl_f, val_lbl / lbl_f.name)

        # dataset.yaml
        yaml_content = f"path: {work_dir}\n"
        yaml_content += "train: images/train\nval: images/val\n"
        yaml_content += f"nc: {len(class_names)}\n"
        yaml_content += f"names: {class_names}\n"
        yaml_path = work_dir / "dataset.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")

        _update_state(status="training", message="YOLO 학습 시작...")

        from ultralytics import YOLO
        model = YOLO("yolov8n.pt")

        model.train(
            data=str(yaml_path),
            epochs=epochs, imgsz=imgsz, batch=batch,
            project=str(work_dir / "runs"), name="train", exist_ok=True,
            verbose=True,
            fliplr=0.0, flipud=0.0,  # LH/RH 구분을 위해 flip 비활성화
            mosaic=1.0, degrees=15.0, translate=0.1, scale=0.3,
        )

        best_pt = work_dir / "runs" / "train" / "weights" / "best.pt"
        if best_pt.exists():
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_name = f"{safe_code}_{ts}.pt"
            out_path = MODELS_DIR / out_name
            shutil.copy2(best_pt, out_path)

            _update_state(status="done", running=False, progress=100,
                          message=f"학습 완료! 모델: {out_name}", model_path=out_name)
            try:
                app.state.detector.load_model(str(out_path))
            except Exception:
                pass
        else:
            _update_state(status="error", running=False,
                          message="best.pt를 찾을 수 없습니다")
    except Exception as e:
        _update_state(status="error", running=False, message=f"학습 오류: {e}")


def _update_state(**kwargs):
    with _training_lock:
        _training_state.update(kwargs)


def _load_classes(path: Path) -> list[str]:
    if path.exists():
        return [l.strip() for l in path.read_text().strip().split("\n") if l.strip()]
    return []


def _merged_classes(product_code: str) -> list[str]:
    """공용 클래스 + 제품별 클래스 병합 (중복 제거, 순서 유지)."""
    common_cls = _load_classes(COMMON_DIR / "classes.txt")
    product_cls = _load_classes(_product_dir(product_code) / "classes.txt")
    merged = list(common_cls)
    for c in product_cls:
        if c not in merged:
            merged.append(c)
    return merged
