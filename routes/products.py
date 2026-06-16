"""제품 + 부자재 CRUD API."""
from fastapi import APIRouter, HTTPException, Request
from db.models import ProductCreate, ProductUpdate, ProductPartCreate, ProductPartUpdate

router = APIRouter(tags=["products"])


# ── 제품 ────────────────────────────────────────────────────

@router.get("/products")
async def list_products(request: Request):
    return request.app.state.db.get_products()


@router.post("/products")
async def create_product(request: Request, body: ProductCreate):
    db = request.app.state.db
    pid = db.create_product(
        name=body.name, code=body.code, car_type=body.car_type,
        model_path=body.model_path,
        face_a_class=body.face_a_class, face_b_class=body.face_b_class,
    )
    return {"id": pid}


@router.get("/products/{product_id}")
async def get_product(request: Request, product_id: int):
    p = request.app.state.db.get_product(product_id)
    if not p:
        raise HTTPException(404, "제품을 찾을 수 없습니다")
    return p


@router.put("/products/{product_id}")
async def update_product(request: Request, product_id: int, body: ProductUpdate):
    fields = body.model_dump(exclude_unset=True)
    request.app.state.db.update_product(product_id, **fields)
    return {"ok": True}


@router.delete("/products/{product_id}")
async def delete_product(request: Request, product_id: int):
    request.app.state.db.delete_product(product_id)
    return {"ok": True}


# ── 부자재 ──────────────────────────────────────────────────

@router.get("/products/{product_id}/parts")
async def list_parts(request: Request, product_id: int):
    return request.app.state.db.get_product_parts(product_id)


@router.post("/products/{product_id}/parts")
async def create_part(request: Request, product_id: int, body: ProductPartCreate):
    db = request.app.state.db
    pid = db.add_product_part(
        product_id=product_id,
        part_type=body.part_type,
        display_name=body.display_name,
        face=body.face,
        required_count=body.required_count,
        yolo_class_name=body.yolo_class_name,
        confidence_threshold=body.confidence_threshold,
    )
    return {"id": pid}


@router.put("/products/{product_id}/parts/{part_id}")
async def update_part(request: Request, product_id: int, part_id: int,
                      body: ProductPartUpdate):
    fields = body.model_dump(exclude_unset=True)
    request.app.state.db.update_product_part(part_id, **fields)
    return {"ok": True}


@router.delete("/products/{product_id}/parts/{part_id}")
async def delete_part(request: Request, product_id: int, part_id: int):
    request.app.state.db.delete_product_part(part_id)
    return {"ok": True}
