/**
 * 제품 관리 페이지 로직
 */

let products = [];
let selectedProductId = null;
let parts = [];
let currentPartsTab = 'A';

// ── 제품 목록 ──────────────────────────────────────────

async function loadProducts() {
    const resp = await fetch('/api/products');
    products = await resp.json();
    renderProducts();
}

function renderProducts() {
    const container = document.getElementById('products-list');
    if (products.length === 0) {
        container.innerHTML = '<div class="card" style="text-align:center; color:#888; padding:40px;">등록된 제품이 없습니다</div>';
        return;
    }

    let html = '<div class="card"><table><thead><tr>';
    html += '<th>품명</th><th>품번</th><th>차종</th><th>상태</th><th>모델</th><th>작업</th>';
    html += '</tr></thead><tbody>';

    for (const p of products) {
        const active = p.is_active ? '<span class="badge badge-active">활성</span>' : '';
        const model = p.model_path || '<span style="color:#666">미설정</span>';
        html += `<tr>
            <td><a href="#" onclick="selectProduct(${p.id}); return false;">${p.name}</a></td>
            <td>${p.code}</td>
            <td>${p.car_type || '-'}</td>
            <td>${active}</td>
            <td style="font-size:12px;">${model}</td>
            <td>
                <button class="btn-primary btn-sm" onclick="editProduct(${p.id})">수정</button>
                <button class="btn-sm" style="background:#444;color:#aaa;" onclick="toggleActive(${p.id}, ${p.is_active})">
                    ${p.is_active ? '비활성화' : '활성화'}
                </button>
                <button class="btn-danger btn-sm" onclick="deleteProduct(${p.id})">삭제</button>
            </td>
        </tr>`;
    }
    html += '</tbody></table></div>';
    container.innerHTML = html;
}

// ── 제품 CRUD ──────────────────────────────────────────

function showAddProduct() {
    document.getElementById('pm-id').value = '';
    document.getElementById('pm-name').value = '';
    document.getElementById('pm-code').value = '';
    document.getElementById('pm-car').value = 'SP3';
    document.getElementById('pm-model').value = '';
    document.getElementById('pm-face-a').value = 'face_a';
    document.getElementById('pm-face-b').value = 'face_b';
    document.getElementById('product-modal-title').textContent = '제품 추가';
    document.getElementById('product-modal').classList.add('active');
}

function editProduct(id) {
    const p = products.find(x => x.id === id);
    if (!p) return;
    document.getElementById('pm-id').value = p.id;
    document.getElementById('pm-name').value = p.name;
    document.getElementById('pm-code').value = p.code;
    document.getElementById('pm-car').value = p.car_type || '';
    document.getElementById('pm-model').value = p.model_path || '';
    document.getElementById('pm-face-a').value = p.face_a_class || '';
    document.getElementById('pm-face-b').value = p.face_b_class || '';
    document.getElementById('product-modal-title').textContent = '제품 수정';
    document.getElementById('product-modal').classList.add('active');
}

function closeProductModal() {
    document.getElementById('product-modal').classList.remove('active');
}

async function saveProduct() {
    const id = document.getElementById('pm-id').value;
    const body = {
        name: document.getElementById('pm-name').value,
        code: document.getElementById('pm-code').value,
        car_type: document.getElementById('pm-car').value,
        model_path: document.getElementById('pm-model').value || null,
        face_a_class: document.getElementById('pm-face-a').value || null,
        face_b_class: document.getElementById('pm-face-b').value || null,
    };

    if (!body.name || !body.code) {
        alert('품명과 품번을 입력하세요');
        return;
    }

    if (id) {
        await fetch(`/api/products/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
    } else {
        await fetch('/api/products', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
    }

    closeProductModal();
    loadProducts();
}

async function deleteProduct(id) {
    if (!confirm('이 제품을 삭제하시겠습니까?')) return;
    await fetch(`/api/products/${id}`, { method: 'DELETE' });
    if (selectedProductId === id) {
        selectedProductId = null;
        document.getElementById('parts-editor').style.display = 'none';
    }
    loadProducts();
}

async function toggleActive(id, currentActive) {
    await fetch(`/api/products/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !currentActive }),
    });
    loadProducts();
}

// ── 부자재 관리 ────────────────────────────────────────

async function selectProduct(id) {
    selectedProductId = id;
    const p = products.find(x => x.id === id);
    document.getElementById('parts-product-name').textContent =
        `부자재 설정 — ${p ? p.name : ''}`;
    document.getElementById('parts-editor').style.display = '';
    await loadParts();
}

async function loadParts() {
    if (!selectedProductId) return;
    const resp = await fetch(`/api/products/${selectedProductId}/parts`);
    parts = await resp.json();
    renderParts();
}

function renderParts() {
    const tbody = document.getElementById('parts-tbody');
    const filtered = parts.filter(p => p.face === currentPartsTab);

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:#666; padding:20px;">
            ${currentPartsTab}면에 등록된 부자재가 없습니다. "부자재 추가"를 클릭하세요.
        </td></tr>`;
        return;
    }

    let html = '';
    for (const p of filtered) {
        html += `<tr>
            <td>${p.part_type}</td>
            <td>${p.display_name}</td>
            <td>${p.face}면</td>
            <td>${p.required_count}</td>
            <td><code style="background:#2a2a4a; padding:2px 6px; border-radius:3px;">${p.yolo_class_name}</code></td>
            <td>${p.confidence_threshold}</td>
            <td>
                <button class="btn-primary btn-sm" onclick="editPart(${p.id})">수정</button>
                <button class="btn-danger btn-sm" onclick="deletePart(${p.id})">삭제</button>
            </td>
        </tr>`;
    }
    tbody.innerHTML = html;
}

function switchPartsTab(face) {
    currentPartsTab = face;
    document.getElementById('pe-tab-a').className = 'face-tab' + (face === 'A' ? ' active' : '');
    document.getElementById('pe-tab-b').className = 'face-tab' + (face === 'B' ? ' active' : '');
    renderParts();
}

// ── 부자재 CRUD ────────────────────────────────────────

function showAddPart() {
    document.getElementById('pt-id').value = '';
    document.getElementById('pt-type').value = '';
    document.getElementById('pt-display').value = '';
    document.getElementById('pt-face').value = currentPartsTab;
    document.getElementById('pt-count').value = '1';
    document.getElementById('pt-yolo').value = '';
    document.getElementById('pt-conf').value = '0.5';
    document.getElementById('part-modal-title').textContent = '부자재 추가';
    document.getElementById('part-modal').classList.add('active');
}

function editPart(id) {
    const p = parts.find(x => x.id === id);
    if (!p) return;
    document.getElementById('pt-id').value = p.id;
    document.getElementById('pt-type').value = p.part_type;
    document.getElementById('pt-display').value = p.display_name;
    document.getElementById('pt-face').value = p.face;
    document.getElementById('pt-count').value = p.required_count;
    document.getElementById('pt-yolo').value = p.yolo_class_name;
    document.getElementById('pt-conf').value = p.confidence_threshold;
    document.getElementById('part-modal-title').textContent = '부자재 수정';
    document.getElementById('part-modal').classList.add('active');
}

function closePartModal() {
    document.getElementById('part-modal').classList.remove('active');
}

async function savePart() {
    const id = document.getElementById('pt-id').value;
    const body = {
        part_type: document.getElementById('pt-type').value,
        display_name: document.getElementById('pt-display').value,
        face: document.getElementById('pt-face').value,
        required_count: parseInt(document.getElementById('pt-count').value) || 1,
        yolo_class_name: document.getElementById('pt-yolo').value,
        confidence_threshold: parseFloat(document.getElementById('pt-conf').value) || 0.5,
    };

    if (!body.part_type || !body.display_name || !body.yolo_class_name) {
        alert('부자재 종류, 표시명, YOLO 클래스명을 모두 입력하세요');
        return;
    }

    if (id) {
        await fetch(`/api/products/${selectedProductId}/parts/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
    } else {
        await fetch(`/api/products/${selectedProductId}/parts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
    }

    closePartModal();
    loadParts();
}

async function deletePart(id) {
    if (!confirm('이 부자재를 삭제하시겠습니까?')) return;
    await fetch(`/api/products/${selectedProductId}/parts/${id}`, { method: 'DELETE' });
    loadParts();
}

// ── 시작 ───────────────────────────────────────────────

loadProducts();
