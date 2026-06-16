"""검사 기록 + 통계 API."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from config import PHOTOS_DIR

router = APIRouter(tags=["inspections"])


@router.get("/inspections")
async def list_inspections(request: Request, date: str = None,
                           product_id: int = None, result: str = None,
                           limit: int = 100, offset: int = 0):
    return request.app.state.db.get_inspections(
        date=date, product_id=product_id, result=result,
        limit=limit, offset=offset,
    )


@router.get("/inspections/{inspection_id}")
async def get_inspection(request: Request, inspection_id: int):
    return request.app.state.db.get_inspection(inspection_id)


@router.get("/inspections/{inspection_id}/photo/{face}")
async def get_photo(request: Request, inspection_id: int, face: str):
    insp = request.app.state.db.get_inspection(inspection_id)
    if not insp:
        return {"error": "검사 기록 없음"}
    photo_path = insp.get(f"{face.lower()}_face_photo")
    if not photo_path:
        return {"error": "사진 없음"}
    full_path = PHOTOS_DIR / photo_path
    if not full_path.exists():
        return {"error": "파일 없음"}
    return FileResponse(str(full_path), media_type="image/jpeg")


@router.get("/stats/today")
async def today_stats(request: Request):
    today = datetime.now().strftime("%Y-%m-%d")
    rows = request.app.state.db.get_daily_stats(date=today)
    total = sum(r["total_count"] for r in rows)
    ok = sum(r["ok_count"] for r in rows)
    ng = sum(r["ng_count"] for r in rows)
    rate = round(ok / total * 100, 1) if total > 0 else 0
    return {
        "date": today, "total": total, "ok": ok, "ng": ng,
        "ok_rate": rate, "by_product": rows,
    }


@router.delete("/stats/today")
async def reset_today_stats(request: Request):
    """오늘 검사 기록 삭제."""
    today = datetime.now().strftime("%Y-%m-%d")
    request.app.state.db.delete_inspections_by_date(today)
    return {"ok": True}


@router.get("/stats/daily")
async def daily_stats(request: Request, date: str = None):
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    rows = request.app.state.db.get_daily_stats(date=date)
    total = sum(r["total_count"] for r in rows)
    ok = sum(r["ok_count"] for r in rows)
    ng = sum(r["ng_count"] for r in rows)
    rate = round(ok / total * 100, 1) if total > 0 else 0
    return {
        "date": date, "total": total, "ok": ok, "ng": ng,
        "ok_rate": rate, "by_product": rows,
    }


@router.get("/stats/range")
async def stats_range(request: Request, start_date: str = None,
                      end_date: str = None):
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        d = datetime.now() - timedelta(days=30)
        start_date = d.strftime("%Y-%m-%d")
    return request.app.state.db.get_stats_range(start_date, end_date)
