# wonjin-qa 프로젝트 종합 가이드

> 다른 프로젝트가 이 시스템의 설계·결정·교훈을 학습/적용하기 위한 단일 참조 문서.
> 최종 정리: 2026-06-02. 본 문서는 코드(`server.py`, `sam2_tracker.py`, `pair_manager.py`,
> `db.py`, `tools/*`)와 운영 메모리(누적 결정사항)를 종합한 것이다.
> ⚠️ 레포 루트의 `README.md` 는 **초기 버전(parts.yaml / YOLOv8n / HuskyLens 시대)** 으로
> 현재 시스템과 다르다. 현재 진실(SoT)은 본 문서와 `docs/SAM2_PIPELINE_RUNBOOK.md` 다.

---

## 0. 한 줄 요약

**사출(plastic injection) 본체 위에 작업자가 부착한 부품들이 모두 제 위치에 설치됐는지를
4K 웹캠 1대로 라이브 검사하는 비전 QA 시스템.** YOLO 검출 + SAM2 인스턴스 추적 +
상태머신 기반 OK/NG 판정으로 동작하며, FastAPI 웹앱(스테이션/대시보드 2-프로세스)으로 운영된다.

---

## 1. 도메인 — 검사 대상 제품

### 1.1 활성 제품: `85875-L2000` (DB product id=3)
- **LH(Left-Hand) + RH(Right-Hand) 좌우 비대칭 "거울상" 제품.** LH/RH 는 서로 거울 반전 형상이라
  육안으로도 좌우 즉시 구분이 어렵다. → 이 한 가지 사실이 시스템의 거의 모든 핵심 결정을 좌우한다.
- **검사 단위 = LH+RH 한 쌍 동시.** 화면에 차례로 등장해도 둘 다 보이면 한 사이클 완료로 본다.
  (단, 트래킹/검사는 각자 독립 인스턴스로 처리. "쌍 묶음"은 운영 단위일 뿐.)
- 부품이 작고(바코드/클립/카바) 본체 굴곡이 많아 복잡도가 높다.

### 1.2 부품 인벤토리 (실물 확정, 2026-05-27)
| side | 검사 대상 부품 | required 개수 |
|---|---|---|
| RH | rh_clip(#3 바 작은클립 + #5 발클립), rh_barcode(노랑) | clip ×2, barcode ×1 |
| LH | lh_clip(#3 + #5), lh_barcode(흰), lh_cover(중앙 구멍 막는 카바, RH엔 없음) | clip ×2, barcode ×1, cover ×1 |

- `#2(통풍클립)`, `#4` 는 **몰딩 일체형이라 검사 대상이 아님.** (영상만으로는 검사대상 vs
  몰딩일체 구분이 불가능 → 실물/도면으로 확정해야 했다.)
- **좌우(LH/RH) 판정의 진짜 단서 = 바코드 색.** 흰색=LH, 노랑=RH. 본체 형상 기반 좌우 판정은
  거울상이라 본질적으로 모호 → 바코드 색/마스크 귀속으로 우회한다.

### 1.3 face 체계
제품 = side(LH/RH) × **face(A/B/C/D)**. 부품이 본체 앞/뒷면 양쪽에서 보일 수 있어 도입.
- A면: 기본 검사면 (suffix 없음).
- B면: LH 만 존재 (`lh_cover_b` 등 `_b` suffix). RH 는 카바가 없어 B면 검사 불필요.
- 명명 규칙: face suffix(`_b`/`_c`/`_d`)는 **항상 클래스 이름 맨 끝**. A면은 suffix 없음.
- **양면 모두 OK 여야 인스턴스 OK.** A면만 충족하면 NG.

---

## 2. 핵심 패러다임 — 검사 방법론의 진화

이 프로젝트의 가장 큰 자산은 "어떻게 검사할 것인가"에 대한 여러 번의 실패와 전환이다.
다른 프로젝트가 반드시 학습해야 할 부분.

### 2.1 폐기된 접근들 (왜 폐기됐는지가 중요)
1. **corner + homography + zone 방식 (폐기)**: 본체 4 corner 검출 → homography → 비율 zone 매핑 →
   부품이 zone 안에 있나 검사. **폐기 이유**: corner 16개 라벨링 부담이 크고, 평면 자세에서만
   동작하며, 비평면(들어올림/뒤집힘)에서 무너짐.
2. **평면 only 검사 (부분 폐기)**: "본체 4 corner 다 보이는 평면 자세에서만 OK/NG, 비평면에선
   트래킹만." 라벨링 부담은 줄였으나 detector 성능/일반화가 약했음.
3. **zone 직접 검출 (개념 OK, 실용성 부족)**: "부품이 zone(장착자리)을 가리니, zone을 부품보다 크게
   잡아 테두리로 위치 검증." → 작은 클립 zone 은 주변 바디 리브와 유사 + 모션블러로 검출 mAP 0.3대.
   카바 zone(0.66)만 그나마 쓸 만. **결론: 정밀 고정카메라 footage 확보 전엔 무리.**

### 2.2 현재 채택된 접근 — **"count 방식"**
> 별도의 NG 클래스/빈 자리 클래스/NG 촬영이 **전혀 필요 없다.**

- **핵심 통찰: 바디만 있고 부품이 없는 상태가 곧 NG 신호다.** 검출기는 맨 바디에선 부품을
  거의 안 잡고(rh_clip ~0.12/frame), 부품이 장착되면 잡는다(~1.3/frame). 이 자연스러운 대비를
  검사 신호로 쓴다.
- **인스턴스별로 부품 검출을 프레임 누적 → required 개수 충족 여부로 OK/NG.**
  - 과거: `robust_count` = `min_support` 프레임 이상에서 관측된 max 개수 (단발 FP 제거 + 가림 복원).
  - 현재 라이브: `fastened[pname]` = 최근 0.5초(15프레임) max count. FP 위험은 PairManager
    hysteresis 가 흡수.
- 부품별 독립 판정이라 "1개만 빠짐"도 자연스럽게 처리되고 missing 부품을 명시할 수 있다.

### 2.3 검출과 추적의 분리
- **detection** 은 "이 자리에 부품이 있나"만 담당.
- **tracking/ReID** 가 "같은 LH 2개 구분 / 인스턴스 영속 ID"를 담당.
- 사용자의 "LH 모델에 RH를 negative 로 넣자" 직관은 **단일 데이터셋 합치기(Stage A)** 로
  자동 달성됨 (RH 프레임이 LH 클래스의 negative 로 작용).

---

## 3. 학습 파이프라인 — SAM2 360° 자동 라벨

전체 재현 런북은 `docs/SAM2_PIPELINE_RUNBOOK.md`. 요약:

```
360° 회전 영상  ──extract_frames──▶  프레임(stride 4)
   │
   │ 사람이 frame 0(+필요시 추가 keyframe)에만 박스+클래스 마킹  (labeler.py)
   ▼
[SAM2 video propagation]  ──▶  전 프레임 자동 라벨 (_auto_filled 점선 박스)
   │   sam2_autolabel.py / sam2_core.propagate()
   ▼
[clean_labels (드리프트 blowup 제거) + render_labels (GUI없는 검수 mp4)]
   ▼
[labels_to_yolo --split temporal]  ──▶  YOLO 데이터셋
   ▼
[DGX 학습: yolo11m/s, imgsz 1280, fliplr=0]  ──▶  best.pt
   ▼
[검증: temporal val mAP + held-out 영상 일반화]
```

### 3.1 왜 SAM2 인가
- 사람은 keyframe 몇 장만 마킹 → SAM2 가 360° 전 회전 + 양손 조작 + self-occlusion 을
  끊김 없이 전파한다 (PoC: 단일 box 1개로 204프레임 lost 0, 손 자동 제외).
- **LLM 프레임 마킹은 폐기** — 정밀도/일관성 부족.
- 멀티객체 전파도 검증됨 (회전으로 사라진 부품이 제 위치에 재획득). hard frame(손가림+급경사)에서만
  마스크가 번져 ~10-20% 사람 보정 필요.

### 3.2 ⚠️ 학습 함정 (반드시 지킬 것)
1. **`fliplr=0.0 flipud=0.0` 필수.** LH/RH 거울상 제품이라 horizontal flip 은 LH↔RH 라벨을
   뒤집어 좌우 구분 능력을 **직접 파괴**한다. ultralytics 기본값이 `fliplr=0.5` 라 반드시
   명시적으로 꺼야 한다. (degrees/mosaic/erasing 등 좌우 안 바꾸는 aug 는 OK)
2. **train/val 은 영상(배치) 단위 temporal split.** `--split temporal --val-ratio 0.2`
   (각 영상의 뒤 20%를 val). **random 분할 절대 금지** — 인접 회전 프레임이 train/val 에
   섞여 mAP 가 비현실적으로 부풀려진다(데이터 누수). 단일바디 영상만 학습하면 2-바디 영상에서
   실패하므로 held-out 영상으로 정직하게 검증할 것.
3. **가중치 파일명에 'sam2' 문자열 금지.** ultralytics 가 SAM 모델로 오인한다.
   로컬 사본은 `body_iter2_noflip_best.pt` 처럼 명명.
4. **경량화보다 성능 우선.** 이 제품은 복잡도가 높아 yolov8n/imgsz 축소 금지. 베이스라인
   yolov8s(또는 yolo11m) + imgsz 1280, 작은 객체 부족하면 1536/1920 로 격상.

### 3.3 학습 인프라 (DGX Spark)
- Host: `edgexpert-e40f.local` (LAN) 또는 `dgx-work`(CF터널 ssh-work.whatisaeo.ai, 외부망).
- GPU: NVIDIA GB10 (Grace Blackwell), Ubuntu 24.04 **aarch64(ARM)**, 128GB 통합메모리.
- NVIDIA Sync 로 passwordless SSH. 작업 디렉토리 `~/wonjin-qa-train/`.
- **GPU 경합 주의**: 같은 DGX 가 vLLM(`vllm-gemma`)을 서빙 중이면 GPU ~85% 점유 → YOLO OOM.
  학습 전 `docker stop vllm-gemma`, 후 `docker start`. (별도 노드가 같은 모델 서빙해 API 안 끊김)
- 데이터 전송 후 **`data.yaml` 의 `path` 를 DGX 절대경로로 수정 필수**(rsync 후).
- 정전 대비: ultralytics `resume=True model=last.pt` 로 재개 가능.

---

## 4. 운영 아키텍처 — 라이브 검사 시스템

### 4.1 2-프로세스 구조 (한 코드베이스, `--mode` 분기)
`server.py` 한 파일이 `--mode station|dashboard` 로 분기, 같은 SQLite DB 를 공유한다.

| | station 모드 (:8000) | dashboard 모드 (:8001) |
|---|---|---|
| 역할 | 카메라/추론/검사 UI/검사 액션 | 입구/대시보드/내역/사용자·제품 관리 |
| 인증 미들웨어 | **비활성** (LAN 신뢰) | **활성** (PUBLIC_PATHS 외 로그인 필요) |
| 카메라/모델 API | 노출 | (관리 위주) |

- 같은 머신에서 두 프로세스가 `data/qa_records.sqlite3` 공유. **SQLite WAL** 로 동시 동작.
- station 의 활성 제품 변경은 capture_loop 가 2초마다 DB 폴링해 감지(cross-process 반영).
- **대시보드가 스테이션 화면을 reverse-proxy** 한다 (CORS/사설IP 회피):
  - `/peers/{name}` (내장 뷰), `/api/peers/{name}/state`, `/.../video.mjpg`(MJPEG proxy),
    `/.../action/{action}`. peer 목록은 `data/peer_stations.json`.
  - 효과: 외부 디바이스(스마트폰)에서 대시보드만 보면 LAN 사설 IP 직접 접근 불필요.

### 4.2 추론 백엔드 — Dual model + SAM2 (현재 production)
station_settings 의 `inference_backend = 'sam2'`, `inference_side = 'both'`.

- **모델: `runs/detect/rh_only_v1/best.pt` + `runs/detect/lh_only_v1/best.pt` (2개 동시)**
  - 각 모델은 자기 side 만 학습 → 반대편 클래스를 아예 모름.
  - SAM2 체크포인트: `checkpoints/sam2.1_hiera_small.pt` (ImagePredictor).
- ⚠️ **왜 dual + 왜 v2 가 폐기됐나** (중요 교훈):
  - 처음엔 단일 멀티클래스 detector → 2-바디 영상에서 LH/RH 혼동, mega-box, ID 파편화.
  - v2 시도: clip 통합 + "크로스 네거티브"(LH 모델에 RH 빈 라벨 50:50). → **실패**.
    거울상이라 크로스 네거티브가 모델을 더 헷갈리게 해 바디 자체를 못 잡음.
  - **최종: v1 dual(각자 자기 side 만 학습) + SAM2 마스크로 인스턴스 귀속.** 검증 통과
    (side_mismatch 113건 → 0건). **학습은 v1, 파이프라인은 unified-clip(clip 단일클래스).**

### 4.3 Decoupled inference (3-스레드, 2026-06-01)
추론이 카메라 fps 를 막지 않도록 추론 블록을 별도 스레드로 분리.
- **capture_loop (메인)**: `cap.read()` → `latest_raw_frame_bgr` 갱신 → 시각화 → JPEG → MJPEG.
  (추론 대기 없이 카메라 fps 따라감)
- **`_inference_thread` (daemon)**: `latest_raw_frame_bgr` 폴링 → `tracker.update` +
  `pair_manager.update` → `instances_snapshot`/`sam2_masks` 갱신.

### 4.4 인스턴스 추적/매칭 정책 (`Sam2InstanceTracker`)
- **SID 할당**: `_alloc_iid()` 가 가장 작은 빈 슬롯 부여(1,2,3…). 화면 ID 항상 1부터.
- **매칭 단계 (side 별 독립)**: ① 마스크 IoU(fallback bbox IoU) 임계 0.15 → ② bbox 중심 거리
  fallback(너비×0.5) → ③ waiting 인스턴스 재사용 fallback(side 같으면 위치 무관, SID 폭증 방지).
- **pending pool (새 인스턴스 생성 게이트)**: 매칭 실패 검출은 즉시 SID 안 줌. 같은 side/위치
  (IoU>0.3) 가 `promote_min_frames=2`회 누적돼야 정식 SID. pending TTL 0.3초. → 한 프레임
  오인식이 SID 안 만든다.
- **NMS (side 무관)**: 한 위치에 LH+RH 동시 fire 시 conf 높은 쪽만 keep (IoU 0.4).
- **Expire**: waiting/working/ok_pending 모두 0.5초로 통일. `active=False`(job 미시작)면 매칭
  후 즉시 정리 → ID 매 사이클 1부터 재사용.
- **재진입 매칭 레이어** (`tools/reentry_tracker.py` 의 ReentryMatcher): BoT-SORT 의 긴 가림
  (track_buffer 90f≈6s) 한계를 넘는 재등장을 같은-클래스 인스턴스에 재연결.
  `--max-per-class 1`(한 쌍 prior)로 phantom 중복 제거.
- **Face hysteresis**: `face_history` deque(maxlen=10) 다수결로 face 안정화.

### 4.5 OK/NG 상태머신 (`PairManager`)
- ROI 기반 finalize. ROI polygon 은 DB station_settings 에 저장.
- hysteresis: `EXIT_HYSTERESIS_SEC = 2.5초`(NG/discard 공통), `OK_EXIT_HYSTERESIS_SEC = 0.5초`.
- **discard 룰**: 부품을 한 번도 안 붙인 인스턴스(`has_been_active=False`)가 ROI 이탈 시 무조건
  discard(NG 아님) → 잘못된 인식이 NG 로 안 남는다.
- `face_ok_since[face]` sticky: 한 face 의 모든 부품 충족 시 영구 기록. 모든 face sticky 되면
  `ok_pending`.
- NG 진단: finalize 시 `missing_parts` 캡처 → DB event detail 에 instance_id/side/body_class/
  missing 저장 → UI 에 `#3 — 클립-RH 0/2` 형식 표시.
- **작업 카운트 = OK 수만.** NG 는 LH/RH side 별 별도 카운터. `commit_session("OK")` 만 호출.

### 4.6 UI (`static/station.{html,css,js}`)
- **NG 풀스크린**: body 직속 z-index 99999, 빨강 깜빡임 + 큰 NG 글자 + 정적 "NG 해제" 버튼.
- **일시정지 풀스크린**: z-index 99998, 어두운 반투명 + "재개" 버튼.
- **인스턴스 카드**: 양면(A/B) 표시, 부품 ✓/□/partial, NG/OK 잠정 카운트다운 진행률 막대.
- **세션 기록**: 메신저 스타일 날짜 separator("— 오늘 2026-06-01 (월) —").
- **SAM2 마스크 시각화**: LH 파랑/RH 주황 alpha 0.4. cv2.putText 는 한글 미지원이라 바디 라벨은
  영문(`ID2 LH [WORKING]`). 한글 오버레이가 필요한 곳은 `text_kr.py`(Pillow+맑은고딕).

---

## 5. 데이터 모델 (SQLite, `data/qa_records.sqlite3`)

`parts.yaml` 은 폐기되고 모든 제품 spec 이 DB 로 이동했다 (다제품 운영 위해).

| 테이블 | 핵심 컬럼 |
|---|---|
| products | id, name(unique), display, settings(JSON), active |
| product_parts | id, product_id, ord, name, display, required, kind('regular'/'assembly'/'zone'), face, reference_corners, expected_zones, UNIQUE(product_id,name) |
| stations | station_id PK, active_product_id |
| jobs | id, station_id, worker_username(**항상 NULL — 폐기됨**), started_ts, ended_ts |
| sessions | id, job_id, station_id, result, duration_sec, last_ng_missing, snapshot_dir, confirmed_by, confirmed_at |
| events | id, job_id, station_id, kind, ts, detail(JSON) |

- station settings 키 예: `inference_backend`, `inference_side`, `model_lh`, `model_rh`,
  ROI polygon, 카메라 해상도 등. 헬퍼: `db.get_station_settings`, `db.update_station_settings`.
- **Worker 역할 완전 폐기**: 모든 사용자는 admin/superadmin. 작업 내역은 **스테이션 단위**로 귀속.
  부팅 시 `ensure_default_admin` 이 옛 worker 를 admin 으로 자동 마이그레이션.

---

## 6. 파일/모듈 맵 (현재 시스템 기준)

### 6.1 라이브 운영 (현재)
| 파일 | 역할 |
|---|---|
| `server.py` | FastAPI 앱. `--mode station\|dashboard`. capture_loop + `_inference_thread` + 모든 route |
| `sam2_tracker.py` | `Sam2InstanceTracker` — dual YOLO 추론 + SAM2 마스크 인스턴스 귀속. 옛 `InstanceTracker` 와 동일 snap 형식 반환(어댑터) |
| `pair_manager.py` | `PairManager` — ROI 기반 OK/NG finalize, hysteresis, missing 캡처 |
| `db.py` | SQLite 스키마/CRUD, station settings, parts.yaml 마이그레이션 |
| `auth.py` | 인증/세션. ROLE_ADMIN 만 assignable |
| `camera.py` | 카메라 소스 헬퍼. DEFAULT_WEBCAM 3840×2160, 미지원 시 fallback |
| `text_kr.py` | 한글 오버레이 (Pillow + 맑은고딕) |
| `static/station.*` | 스테이션 검사 UI |
| `static/dashboard.*`, `history.*`, `products.*`, `users.*`, `models.*`, `peer_view.*` | 대시보드/관리 UI |

### 6.2 학습/데이터 파이프라인 도구 (`tools/`)
| 도구 | 역할 |
|---|---|
| `extract_frames.py` | 영상 → 프레임(stride/max-w) |
| `sam2_core.py` / `sam2_autolabel.py` / `sam2_propagate.py` | SAM2 전파 자동라벨 코어/실행/PoC |
| `clean_labels.py` | `_auto_filled` 드리프트 blowup(면적 이상치) 자동 제거 |
| `render_labels.py` | GUI 없이 라벨 overlay+mp4 검수 |
| `labels_to_yolo.py` | labelme→YOLO (`--classes`, `--split temporal`) |
| `migrate_classes_zones.py` | corner 제거 + zone 추가 클래스 마이그레이션 |
| `build_v2_side_datasets.py` | (폐기된 v2) 크로스-네거티브 데이터셋 빌더 |
| `reentry_tracker.py` | BoT-SORT+ReID+재진입 (`--max-per-class`) |
| `botsort_reid.yaml` | BoT-SORT 설정(with_reid=True, track_buffer=90, gmc=none) |
| `barcode_side.py` | 바코드색 좌우 판정(구 HSV 휴리스틱; 학습 검출로 대체됨) |
| `run_pipeline.py` / `run_pipeline_sam2.py` | 검출+추적+재진입+좌우+검사 통합 실행 |
| `seed_product_85875.py` / `seed_85875_b_face.py` / `rename_85875_parts.py` | 제품/부품 DB 시드·재명명 |
| `burn_rpi_sd.py` / `build_station_sd.py` / `station_image/` | RPi 키오스크 빌더(**현재 보류**) |

### 6.3 `labeler.py` (자체 라벨링 도구)
- Roboflow/AnyLabeling 대신 자체 구현 (의존성 없음). OpenCV GUI.
- DB 에서 클래스 로드, 단축키, LH/RH/공통 그룹 자동 분리, 칩 클릭 선택, 한글 IME 키 매핑.
- `_side_from_name` 이 `zone_` 접두를 strip 해 zone_lh_*→LH 그룹/색상 유지.
- keyframe 마킹 + SAM2 전파 결과(점선 박스) 리뷰/수정 모두 이 도구로.

### 6.4 폐기/역사적 (참고만)
- `inspect_live.py`, `detector.py`, `orientation.py`, `checklist.py`, `prepare_dataset.py`,
  `capture_data.py` — 초기 단일모델 + 방향분류기 + 체크리스트 시대. `README.md` 가 설명하는 게 이것.
  현재 운영엔 안 쓰임(detector.py 는 시각화용 잔존, sam2 backend 에선 불필요).
- `parts.yaml` — DB 로 대체되어 폐기.

---

## 7. 실행 방법 (현재 운영)

```bash
# 의존성 (requirements.txt): opencv-python, Pillow, PyYAML, ultralytics,
#                            fastapi, uvicorn, httpx  (+ 로컬에 sam2)
# SAM2 체크포인트: checkpoints/sam2.1_hiera_small.pt

# 1) backend 가 sam2 인지 확인 (반드시 dual 모드)
.venv/bin/python -c "import db; db.init_db(); print(db.get_station_settings('S01').get('inference_backend'))"
# → 'sam2' 이어야 함. 아니면:
.venv/bin/python -c "import db; db.init_db(); db.update_station_settings('S01', {'inference_backend':'sam2','inference_side':'both'})"

# 2) 스테이션 실행
.venv/bin/python server.py                      # 또는 --mode station --port 8000
#   부트 로그에 [sam2tracker] init device=mps imgsz=1280 ... 확인
#   브라우저: http://localhost:8000/station

# 3) 대시보드 실행 (별도 프로세스)
.venv/bin/python server.py --mode dashboard --port 8001
```

> ⚠️ **테스트 시 항상 dual 모델(sam2 backend) 로 띄울 것.** 단일 모델(`backend='local'`)이나
> remote 로 띄우면 안 된다 — 현재 production 정책.

---

## 8. 다른 프로젝트가 가져갈 재사용 가능한 패턴/교훈

1. **"없는 게 곧 NG" 신호** — 별도 NG 클래스나 결함 데이터 촬영 없이, 정상 부품의 검출 유무
   대비만으로 검사. 데이터 수집 비용을 극적으로 줄인다.
2. **검출과 추적의 분리** — 외관이 거의 동일한 다중 인스턴스 구분은 detector 가 아니라 추적/ReID/
   보조신호(여기선 바코드 색)의 몫. detector 에 과부하 주지 말 것.
3. **거울상/대칭 객체엔 flip augmentation 금지** — 좌우 라벨을 파괴. 프레임워크 기본값 확인 필수.
4. **인접 프레임 누수 방지를 위한 temporal split** — 영상에서 데이터셋 만들 때 random 분할은
   mAP 를 거짓으로 부풀린다. held-out 영상으로 정직 검증.
5. **SAM2 video propagation 으로 라벨링 자동화** — keyframe 몇 장만 사람이, 나머지는 전파.
   드리프트는 면적 이상치 자동 제거 + 사람 ~10-20% 보정.
6. **단일 코드베이스 + `--mode` 2-프로세스** — 검사용/관리용 관심사를 인증 미들웨어 on/off 로
   분리하되 같은 DB 공유. 대시보드가 스테이션을 reverse-proxy 해 CORS/사설IP 문제 회피.
7. **decoupled inference 스레드** — 추론이 카메라 fps/스트림을 막지 않도록 분리.
8. **pending pool + hysteresis** — 한 프레임 오인식이 ID/NG 를 만들지 않게 하는 게이트.
   라이브 비전 안정성의 핵심.
9. **무거운 실패를 기록하라** — 이 프로젝트의 가치 절반은 "왜 corner/zone/v2 가 폐기됐는지"의
   기록이다. 폐기된 접근의 이유를 남겨야 같은 함정을 반복하지 않는다.
10. **GPU 경합 운영** — 같은 서버가 학습 GPU 와 LLM 서빙을 공유하면 OOM. 학습 전 서빙 컨테이너
    정지 + 별도 노드 페일오버.

---

## 9. 현재 상태 / 미해결 (2026-06-02 기준)

- ✅ server.py + Sam2InstanceTracker 통합 + decoupled inference 운영 중 (v1 dual + SAM2).
- ✅ 두-바디 검사 시나리오 통과 (ID1 RH / ID2 LH 각자 OK/NG 판정).
- ⏳ face B 실 라이브 검증 미완 (`lh_only_v1` 에 lh_cover_b 클래스 존재).
- ⏳ 부분-NG(부품 1개만 빠짐) 실 footage 검증 미완 (지금까지 학습영상 평가라 낙관적).
- ⏳ rh_clip recall 이 모션블러 프레임에서 낮음 (인스턴스 누적으로 복원되나 깨끗한 고정카메라
  footage 로 보강 권장).
- ⏸ zone 정밀 위치검증, RPi 키오스크 포팅(Hailo AI Kit 경로) — 보류.
- 📌 DGX 는 YOLO 학습 + vLLM(Nemotron-120B / Gemma) 외부 API 서빙을 겸함 (`/Users/yg/d/dgx-vllm/`).

---

## 10. 참조 문서
- `docs/SAM2_PIPELINE_RUNBOOK.md` — 학습 파이프라인 전 과정 재현 명령어 + 함정.
- `README.md` — ⚠️ 초기 버전(역사적 참고용, 현재 시스템과 다름).
- 백업: `.backup_pre_decouple_20260601_194933/` (decoupled inference 적용 직전 상태).
