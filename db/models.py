"""Pydantic 모델 — API 입출력 스키마."""
from pydantic import BaseModel
from typing import Optional


class ProductCreate(BaseModel):
    name: str
    code: str
    car_type: str = ""
    model_path: Optional[str] = None
    face_a_class: Optional[str] = None
    face_b_class: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    car_type: Optional[str] = None
    model_path: Optional[str] = None
    face_a_class: Optional[str] = None
    face_b_class: Optional[str] = None
    is_active: Optional[bool] = None


class ProductPartCreate(BaseModel):
    part_type: str
    display_name: str
    face: str  # "A" or "B"
    required_count: int = 1
    yolo_class_name: str
    confidence_threshold: float = 0.5


class ProductPartUpdate(BaseModel):
    display_name: Optional[str] = None
    required_count: Optional[int] = None
    yolo_class_name: Optional[str] = None
    confidence_threshold: Optional[float] = None
    face: Optional[str] = None


class SettingsUpdate(BaseModel):
    camera_index: Optional[int] = None
    camera_width: Optional[int] = None
    camera_height: Optional[int] = None
    confidence_threshold: Optional[float] = None
    demo_mode: Optional[bool] = None
