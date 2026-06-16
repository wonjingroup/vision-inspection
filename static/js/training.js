/**
 * AI 학습 페이지 — 데이터 수집 + 라벨링 + YOLO 학습
 * 마킹 모드: 박스 / 원형 / 자유형(폴리곤)
 */

// ── 상태 ───────────────────────────────────────────────

let selectedProductCode = 'default';
let classNames = [];
let selectedClass = null;
let selectedShape = 'box';   // 'box' | 'circle' | 'freeform'
let currentImage = null;
let labels = [];             // [{class_name, shape, ...shape-specific}]
let images = [];
let isDirty = false;

// 드래그 상태 (box, circle)
let isDrawing = false;
let drawStart = { x: 0, y: 0 };
let drawEnd = { x: 0, y: 0 };

// 자유형 상태
let freeformPoints = [];     // 현재 그리는 중인 폴리곤 점들 (캔버스 좌표)

// 캔버스
const canvas = document.getElementById('label-canvas');
const ctx = canvas.getContext('2d');
let imgObj = null;
let scale = 1;
let offsetX = 0, offsetY = 0;

const CLASS_COLORS = [
    '#4caf50', '#f44336', '#2196f3', '#ff9800', '#9c27b0',
    '#00bcd4', '#ffeb3b', '#e91e63', '#8bc34a', '#ff5722',
    '#3f51b5', '#009688', '#ffc107', '#795548', '#607d8b',
];

function getClassColor(name) {
    const idx = classNames.indexOf(name);
    return CLASS_COLORS[idx % CLASS_COLORS.length];
}

// ── 초기화 ─────────────────────────────────────────────

async function init() {
    try {
        await loadProducts();
        await loadClasses();
        await loadImages();
        await loadDatasetStats();
        renderClassButtons();
        setupCanvas();
        updateShapeButtons();
        console.log('[training] init 완료, product:', selectedProductCode);
    } catch (e) {
        console.error('[training] init 오류:', e);
    }
}

// ── 마킹 모드 선택 ────────────────────────────────────

function setShape(shape) {
    // 자유형 그리던 중이면 취소
    if (freeformPoints.length > 0) {
        freeformPoints = [];
        redraw();
    }
    selectedShape = shape;
    updateShapeButtons();
    canvas.style.cursor = shape === 'freeform' ? 'crosshair' : 'crosshair';
}

function updateShapeButtons() {
    document.querySelectorAll('.shape-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.shape === selectedShape);
    });
}

// ── 제품 선택 ─────────────────────────────────────────

async function loadProducts() {
    try {
        const resp = await fetch('/api/products');
        const products = await resp.json();
        const container = document.getElementById('product-selector');
        container.innerHTML = '';
        if (products.length === 0) {
            container.innerHTML = '<span style="color:#666;font-size:12px;">등록된 제품 없음</span>';
            return;
        }
        products.forEach(p => {
            const chip = document.createElement('div');
            chip.className = 'product-chip' + (p.code === selectedProductCode ? ' active' : '');
            chip.textContent = p.code || p.name;
            chip.onclick = () => selectProduct(p.code || 'default');
            container.appendChild(chip);
        });
        if (selectedProductCode === 'default' && products.length > 0 && products[0].code) {
            selectedProductCode = products[0].code;
            loadProducts();
        }
    } catch (e) {}
}

async function selectProduct(code) {
    if (isDirty && currentImage) {
        if (confirm('변경사항을 저장하시겠습니까?')) await saveLabels();
    }
    selectedProductCode = code;
    currentImage = null;
    labels = [];
    freeformPoints = [];
    clearCanvas();
    await loadProducts();
    await loadClasses();
    await loadImages();
    await loadDatasetStats();
    renderClassButtons();
    renderLabelList();
}

// ── 클래스 관리 ────────────────────────────────────────

async function loadClasses() {
    const resp = await fetch(`/api/training/classes?product_code=${encodeURIComponent(selectedProductCode)}`);
    const data = await resp.json();
    classNames = data.class_names || [];
    if (classNames.length > 0 && !selectedClass) {
        selectedClass = classNames[0];
    }
}

function renderClassButtons() {
    const container = document.getElementById('class-buttons');
    container.innerHTML = '';
    classNames.forEach((name, i) => {
        const btn = document.createElement('button');
        btn.className = 'class-btn' + (name === selectedClass ? ' active' : '');
        btn.style.background = getClassColor(name);
        btn.style.color = '#fff';
        btn.textContent = name;
        btn.onclick = () => { selectedClass = name; renderClassButtons(); };
        container.appendChild(btn);
    });
}

function showAddClass() {
    document.getElementById('new-class-name').value = '';
    document.getElementById('class-modal').classList.add('active');
    document.getElementById('new-class-name').focus();
}

function closeClassModal() {
    document.getElementById('class-modal').classList.remove('active');
}

function quickAdd(name) {
    document.getElementById('new-class-name').value = name;
    addClass();
}

async function addClass() {
    const name = document.getElementById('new-class-name').value.trim();
    if (!name) return;
    if (classNames.includes(name)) { alert('이미 존재하는 클래스입니다'); return; }
    classNames.push(name);
    await fetch(`/api/training/classes?product_code=${encodeURIComponent(selectedProductCode)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ class_names: classNames }),
    });
    if (!selectedClass) selectedClass = name;
    renderClassButtons();
    closeClassModal();
}

// ── 이미지 관리 ────────────────────────────────────────

async function loadImages() {
    const resp = await fetch(`/api/training/images?product_code=${encodeURIComponent(selectedProductCode)}`);
    images = await resp.json();
    renderImageGrid();
    const el = document.getElementById('img-count');
    if (el) el.textContent = `${images.length}장`;
}

function renderImageGrid() {
    const grid = document.getElementById('image-grid');
    grid.innerHTML = '';
    if (images.length === 0) {
        grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; color:#666; padding:20px; font-size:13px;">촬영된 이미지가 없습니다</div>';
        return;
    }
    images.forEach(img => {
        const div = document.createElement('div');
        div.className = 'image-thumb';
        if (currentImage && currentImage.filename === img.filename) div.classList.add('active');
        if (img.has_label) {
            div.classList.add('labeled');
            div.dataset.count = img.label_count;
        } else {
            div.classList.add('unlabeled');
        }
        const imgSource = img.source === 'common' ? 'common' : selectedProductCode;
        div.innerHTML = `
            <img src="${img.url}" loading="lazy">
            <button class="delete-btn" onclick="event.stopPropagation(); deleteImage('${img.filename}', '${imgSource}')" title="삭제">X</button>
        `;
        div.onclick = () => selectImage(img);
        grid.appendChild(div);
    });
}

async function captureFrame() {
    try {
        const resp = await fetch(`/api/training/capture?product_code=${encodeURIComponent(selectedProductCode)}`, { method: 'POST' });
        const data = await resp.json();
        if (data.error) { alert(data.error); return; }
        await loadImages();
        await loadDatasetStats();
        selectImage({ filename: data.filename, url: data.url, width: data.width, height: data.height });
    } catch (e) {
        alert('촬영 오류: ' + e.message);
    }
}

async function deleteImage(filename, source) {
    if (!confirm('이미지와 라벨을 삭제하시겠습니까?')) return;
    const code = source || selectedProductCode;
    await fetch(`/api/training/images/${encodeURIComponent(code)}/${filename}`, { method: 'DELETE' });
    if (currentImage && currentImage.filename === filename) {
        currentImage = null;
        labels = [];
        clearCanvas();
    }
    await loadImages();
    await loadDatasetStats();
}

async function selectImage(img) {
    if (isDirty && currentImage) {
        if (confirm('변경사항을 저장하시겠습니까?')) await saveLabels();
    }
    currentImage = img;
    freeformPoints = [];
    renderImageGrid();

    const resp = await fetch(`/api/training/labels/${encodeURIComponent(selectedProductCode)}/${img.filename}`);
    const data = await resp.json();
    labels = data.labels || [];
    if (data.class_names && data.class_names.length > classNames.length) {
        classNames = data.class_names;
        renderClassButtons();
    }
    isDirty = false;

    imgObj = new Image();
    imgObj.onload = () => {
        fitCanvas();
        redraw();
        document.getElementById('canvas-hint').style.display = 'none';
    };
    imgObj.src = img.url;
    renderLabelList();
}

// ── 캔버스 ─────────────────────────────────────────────

function setupCanvas() {
    canvas.addEventListener('mousedown', onMouseDown);
    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseup', onMouseUp);
    canvas.addEventListener('dblclick', onDblClick);
    canvas.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        // 우클릭으로 자유형 완료
        if (selectedShape === 'freeform' && freeformPoints.length >= 3) {
            commitFreeform();
        }
    });
    window.addEventListener('resize', () => { if (imgObj) { fitCanvas(); redraw(); } });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'z' && e.ctrlKey) { e.preventDefault(); undoLabel(); }
        if (e.key === 's' && e.ctrlKey) { e.preventDefault(); saveLabels(); }
        if (e.key === 'Escape' && selectedShape === 'freeform' && freeformPoints.length > 0) {
            freeformPoints = [];
            redraw();
        }
    });
}

function fitCanvas() {
    const wrapper = canvas.parentElement;
    const wW = wrapper.clientWidth;
    const wH = wrapper.clientHeight;
    const iW = imgObj.naturalWidth;
    const iH = imgObj.naturalHeight;
    scale = Math.min(wW / iW, wH / iH, 1);
    canvas.width = Math.floor(iW * scale);
    canvas.height = Math.floor(iH * scale);
}

function clearCanvas() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    document.getElementById('canvas-hint').style.display = '';
}

// ── 그리기 ─────────────────────────────────────────────

function redraw() {
    if (!imgObj) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(imgObj, 0, 0, canvas.width, canvas.height);

    // 저장된 라벨 그리기
    labels.forEach(lbl => drawLabel(lbl));

    // 드래그 중인 미리보기
    const color = selectedClass ? getClassColor(selectedClass) : '#fff';
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.setLineDash([5, 3]);

    if (isDrawing && selectedShape === 'box') {
        const x = Math.min(drawStart.x, drawEnd.x);
        const y = Math.min(drawStart.y, drawEnd.y);
        ctx.strokeRect(x, y, Math.abs(drawEnd.x - drawStart.x), Math.abs(drawEnd.y - drawStart.y));
    } else if (isDrawing && selectedShape === 'circle') {
        const r = Math.hypot(drawEnd.x - drawStart.x, drawEnd.y - drawStart.y);
        ctx.beginPath();
        ctx.arc(drawStart.x, drawStart.y, r, 0, Math.PI * 2);
        ctx.stroke();
    }

    // 자유형 진행 중
    if (freeformPoints.length > 0) {
        ctx.beginPath();
        ctx.moveTo(freeformPoints[0].x, freeformPoints[0].y);
        for (let i = 1; i < freeformPoints.length; i++) {
            ctx.lineTo(freeformPoints[i].x, freeformPoints[i].y);
        }
        ctx.stroke();
        // 점 표시
        freeformPoints.forEach(p => {
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
            ctx.fill();
        });
    }
    ctx.setLineDash([]);
}

function drawLabel(lbl) {
    const color = getClassColor(lbl.class_name);
    const shape = lbl.shape || 'box';
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;

    let labelX, labelY;

    if (shape === 'box') {
        const x = (lbl.cx - lbl.w / 2) * canvas.width;
        const y = (lbl.cy - lbl.h / 2) * canvas.height;
        const w = lbl.w * canvas.width;
        const h = lbl.h * canvas.height;
        ctx.strokeRect(x, y, w, h);
        labelX = x;
        labelY = y;
    } else if (shape === 'circle') {
        const cx = lbl.cx * canvas.width;
        const cy = lbl.cy * canvas.height;
        const r = lbl.r * canvas.width;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.stroke();
        labelX = cx - r;
        labelY = cy - r;
    } else if (shape === 'freeform' && lbl.points) {
        const pts = lbl.points.map(p => ({ x: p.x * canvas.width, y: p.y * canvas.height }));
        if (pts.length < 2) return;
        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
        ctx.closePath();
        ctx.stroke();
        // 반투명 채우기
        ctx.fillStyle = color + '20';
        ctx.fill();
        labelX = pts[0].x;
        labelY = pts[0].y;
    }

    // 클래스명 태그
    if (labelX !== undefined) {
        const shapeIcon = shape === 'box' ? '▭' : shape === 'circle' ? '○' : '◇';
        const text = `${shapeIcon} ${lbl.class_name}`;
        ctx.font = '12px Malgun Gothic, sans-serif';
        const tm = ctx.measureText(text);
        ctx.fillStyle = color;
        ctx.fillRect(labelX, labelY - 18, tm.width + 8, 18);
        ctx.fillStyle = '#fff';
        ctx.fillText(text, labelX + 4, labelY - 4);
    }
}

// ── 마우스 이벤트 ──────────────────────────────────────

function getCanvasPos(e) {
    const rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}

function checkClassSelected() {
    if (!imgObj) return false;
    if (!selectedClass && classNames.length > 0) { alert('먼저 클래스를 선택하세요'); return false; }
    if (classNames.length === 0) { alert('먼저 +추가 버튼으로 클래스를 등록하세요'); return false; }
    return true;
}

function onMouseDown(e) {
    if (selectedShape === 'freeform') return; // 자유형은 click으로 처리
    if (!checkClassSelected()) return;
    isDrawing = true;
    drawStart = getCanvasPos(e);
    drawEnd = { ...drawStart };
}

function onMouseMove(e) {
    if (!isDrawing) return;
    drawEnd = getCanvasPos(e);
    redraw();
}

function onMouseUp(e) {
    if (selectedShape === 'freeform') return;
    if (!isDrawing) return;
    isDrawing = false;
    drawEnd = getCanvasPos(e);

    if (selectedShape === 'box') {
        commitBox();
    } else if (selectedShape === 'circle') {
        commitCircle();
    }
}

function onDblClick(e) {
    if (selectedShape === 'freeform' && freeformPoints.length >= 3) {
        commitFreeform();
    }
}

// 자유형: 클릭으로 점 추가
canvas.addEventListener('click', (e) => {
    if (selectedShape !== 'freeform') return;
    if (!checkClassSelected()) return;
    const pos = getCanvasPos(e);
    freeformPoints.push(pos);
    redraw();
});

// ── 마킹 커밋 ─────────────────────────────────────────

function commitBox() {
    const x1 = Math.min(drawStart.x, drawEnd.x);
    const y1 = Math.min(drawStart.y, drawEnd.y);
    const x2 = Math.max(drawStart.x, drawEnd.x);
    const y2 = Math.max(drawStart.y, drawEnd.y);
    if (x2 - x1 < 5 || y2 - y1 < 5) { redraw(); return; }

    labels.push({
        class_name: selectedClass,
        shape: 'box',
        cx: ((x1 + x2) / 2) / canvas.width,
        cy: ((y1 + y2) / 2) / canvas.height,
        w: (x2 - x1) / canvas.width,
        h: (y2 - y1) / canvas.height,
    });
    isDirty = true;
    redraw();
    renderLabelList();
}

function commitCircle() {
    const r = Math.hypot(drawEnd.x - drawStart.x, drawEnd.y - drawStart.y);
    if (r < 5) { redraw(); return; }

    labels.push({
        class_name: selectedClass,
        shape: 'circle',
        cx: drawStart.x / canvas.width,
        cy: drawStart.y / canvas.height,
        r: r / canvas.width,
    });
    isDirty = true;
    redraw();
    renderLabelList();
}

function commitFreeform() {
    if (freeformPoints.length < 3) return;
    const points = freeformPoints.map(p => ({
        x: p.x / canvas.width,
        y: p.y / canvas.height,
    }));
    labels.push({
        class_name: selectedClass,
        shape: 'freeform',
        points: points,
    });
    freeformPoints = [];
    isDirty = true;
    redraw();
    renderLabelList();
}

// ── 라벨 관리 ──────────────────────────────────────────

function renderLabelList() {
    const ul = document.getElementById('label-list');
    if (labels.length === 0) {
        ul.innerHTML = '<li style="color:#666;">라벨 없음 — 마킹을 그리세요</li>';
        return;
    }
    ul.innerHTML = '';
    labels.forEach((lbl, i) => {
        const li = document.createElement('li');
        const shape = lbl.shape || 'box';
        const icon = shape === 'box' ? '▭' : shape === 'circle' ? '○' : '◇';
        let size = '';
        if (shape === 'box') size = `${(lbl.w * 100).toFixed(0)}x${(lbl.h * 100).toFixed(0)}%`;
        else if (shape === 'circle') size = `r=${(lbl.r * 100).toFixed(0)}%`;
        else if (shape === 'freeform') size = `${lbl.points.length}점`;

        li.innerHTML = `
            <span class="label-color" style="background:${getClassColor(lbl.class_name)}"></span>
            <span>${icon} ${lbl.class_name}</span>
            <span style="color:#666; font-size:11px;">(${size})</span>
            <button class="del-btn" onclick="removeLabel(${i})">x</button>
        `;
        li.addEventListener('mouseenter', () => highlightLabel(i));
        li.addEventListener('mouseleave', () => redraw());
        ul.appendChild(li);
    });
}

function removeLabel(idx) {
    labels.splice(idx, 1);
    isDirty = true;
    redraw();
    renderLabelList();
}

function undoLabel() {
    if (freeformPoints.length > 0) {
        freeformPoints.pop();
        redraw();
        return;
    }
    if (labels.length === 0) return;
    labels.pop();
    isDirty = true;
    redraw();
    renderLabelList();
}

function highlightLabel(idx) {
    redraw();
    const lbl = labels[idx];
    const shape = lbl.shape || 'box';
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 3;

    if (shape === 'box') {
        const x = (lbl.cx - lbl.w / 2) * canvas.width;
        const y = (lbl.cy - lbl.h / 2) * canvas.height;
        ctx.strokeRect(x - 1, y - 1, lbl.w * canvas.width + 2, lbl.h * canvas.height + 2);
    } else if (shape === 'circle') {
        ctx.beginPath();
        ctx.arc(lbl.cx * canvas.width, lbl.cy * canvas.height, lbl.r * canvas.width + 2, 0, Math.PI * 2);
        ctx.stroke();
    } else if (shape === 'freeform' && lbl.points) {
        const pts = lbl.points.map(p => ({ x: p.x * canvas.width, y: p.y * canvas.height }));
        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
        ctx.closePath();
        ctx.stroke();
    }
}

// ── 저장/로드 ─────────────────────────────────────────

async function saveLabels() {
    if (!currentImage) { alert('이미지를 선택하세요'); return; }
    await fetch(`/api/training/labels/${encodeURIComponent(selectedProductCode)}/${currentImage.filename}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ labels, class_names: classNames }),
    });
    isDirty = false;
    await loadImages();
    await loadDatasetStats();
}

// ── 데이터셋 통계 ──────────────────────────────────────

async function loadDatasetStats() {
    const resp = await fetch(`/api/training/stats?product_code=${encodeURIComponent(selectedProductCode)}`);
    const s = await resp.json();
    const elLabeled = document.getElementById('ds-labeled');
    const elUnlabeled = document.getElementById('ds-unlabeled');
    if (elLabeled) elLabeled.textContent = s.labeled_images;
    if (elUnlabeled) elUnlabeled.textContent = s.unlabeled_images;
}

// ── 학습 ───────────────────────────────────────────────

async function startTraining() {
    const epochs = parseInt(document.getElementById('train-epochs').value) || 100;
    const batch = parseInt(document.getElementById('train-batch').value) || 8;
    const resp = await fetch('/api/training/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_code: selectedProductCode, epochs, batch, imgsz: 640 }),
    });
    const data = await resp.json();
    if (data.error) { alert(data.error); return; }
    document.getElementById('train-btn').disabled = true;
    document.getElementById('train-btn').textContent = '학습 중...';
    document.getElementById('train-progress-bar').style.display = '';
    pollTraining();
}

async function pollTraining() {
    try {
        const resp = await fetch('/api/training/status');
        const s = await resp.json();
        document.getElementById('train-status').textContent = s.message;
        document.getElementById('train-progress-fill').style.width = s.progress + '%';
        if (s.status === 'done') {
            document.getElementById('train-btn').disabled = false;
            document.getElementById('train-btn').textContent = '학습 시작';
            document.getElementById('train-status').innerHTML = `<span style="color:#4caf50;">${s.message}</span>`;
            alert('학습 완료! 모델: ' + s.model_path);
            return;
        }
        if (s.status === 'error') {
            document.getElementById('train-btn').disabled = false;
            document.getElementById('train-btn').textContent = '학습 시작';
            document.getElementById('train-status').innerHTML = `<span style="color:#f44336;">${s.message}</span>`;
            return;
        }
        if (s.running) setTimeout(pollTraining, 2000);
    } catch (e) { setTimeout(pollTraining, 3000); }
}

// ── 시작 ───────────────────────────────────────────────

init();
