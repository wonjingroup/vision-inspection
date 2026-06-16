/**
 * 메인 검사 화면 로직
 * - /api/status 폴링으로 검사 상태 실시간 갱신
 * - OK/NG 오버레이 + 사운드 트리거
 */

let prevState = 'idle';
let okShown = false;
let ngShown = false;
let activeFaceTab = 'A';
let statsRefreshTimer = null;

// ── 상태 폴링 ──────────────────────────────────────────

async function pollStatus() {
    try {
        const resp = await fetch('/api/status');
        const s = await resp.json();
        updateUI(s);
    } catch (e) {
        document.getElementById('camera-status').textContent = '연결 끊김';
    }
    setTimeout(pollStatus, 200);
}

function updateUI(s) {
    const state = s.state;

    // 카메라 상태
    document.getElementById('camera-status').textContent =
        state === 'standby' ? '대기 중' : (state === 'idle' ? '제품 대기' : '검사 중');

    // 상태 뱃지
    const badge = document.getElementById('state-badge');
    const stateLabels = {
        standby: '검사시작 대기',
        idle: '제품 인식 대기...',
        detecting: '제품 감지...',
        inspecting_a: 'A면 검사 중',
        inspecting_b: 'B면 검사 중',
        judging: '판정 중...',
        result_ok: 'OK',
        result_ng: 'NG',
    };
    badge.textContent = stateLabels[state] || state;
    badge.className = 'state-badge';
    if (state === 'standby') badge.classList.add('state-idle');
    else if (state === 'idle') badge.classList.add('state-inspecting');
    else if (state.startsWith('inspecting')) badge.classList.add('state-inspecting');
    else if (state === 'result_ok') badge.classList.add('state-result-ok');
    else if (state === 'result_ng') badge.classList.add('state-result-ng');

    // 버튼 전환: standby일 때 검사시작, 그 외엔 검사 중단
    const btnStart = document.getElementById('btn-start');
    const btnReset = document.getElementById('btn-reset');
    if (state === 'standby') {
        btnStart.style.display = '';
        btnReset.style.display = 'none';
    } else {
        btnStart.style.display = 'none';
        btnReset.style.display = '';
    }

    // 경과 시간 (standby에서는 숨김)
    const elapsed = document.getElementById('elapsed');
    if (state === 'standby') {
        elapsed.textContent = '';
    } else {
        elapsed.textContent = s.elapsed_sec > 0 ? `${s.elapsed_sec}s` : '';
    }

    // 제품 정보
    const info = document.getElementById('product-info');
    if (s.product_name) {
        info.textContent = `${s.product_name}${s.product_code ? ' (' + s.product_code + ')' : ''}`;
    } else if (state === 'standby') {
        info.textContent = '검사시작 버튼을 눌러주세요';
    } else {
        info.textContent = '제품을 카메라에 보여주세요';
    }

    // 면 탭 업데이트
    const tabA = document.getElementById('tab-a');
    const tabB = document.getElementById('tab-b');
    tabA.className = 'face-tab';
    tabB.className = 'face-tab';
    if (state === 'inspecting_a') {
        tabA.classList.add('inspecting');
        activeFaceTab = 'A';
    } else if (state === 'inspecting_b') {
        tabB.classList.add('inspecting');
        activeFaceTab = 'B';
    }
    if (activeFaceTab === 'A') tabA.classList.add('active');
    else tabB.classList.add('active');

    // 부자재 체크리스트
    updatePartsList('parts-a', s.face_a_parts || {});
    updatePartsList('parts-b', s.face_b_parts || {});
    document.getElementById('parts-a').style.display = activeFaceTab === 'A' ? '' : 'none';
    document.getElementById('parts-b').style.display = activeFaceTab === 'B' ? '' : 'none';

    // OK/NG 오버레이 제어
    if (state === 'result_ok' && prevState !== 'result_ok') {
        showOk(s);
    } else if (state === 'result_ng' && prevState !== 'result_ng') {
        showNg(s);
    } else if (state !== 'result_ok' && state !== 'result_ng') {
        hideOverlays();
    }

    // OK 상태에서 벗어나면 오버레이 숨기기
    if (state !== 'result_ok' && okShown) {
        hideOverlays();
    }

    prevState = state;
}

function updatePartsList(elemId, parts) {
    const ul = document.getElementById(elemId);
    if (!parts || Object.keys(parts).length === 0) {
        ul.innerHTML = '<li class="pending"><span class="icon pending">-</span>등록된 부자재 없음</li>';
        return;
    }

    let html = '';
    for (const [ptype, info] of Object.entries(parts)) {
        const cls = info.ok ? 'ok' : (info.actual > 0 ? 'ng' : 'pending');
        const icon = info.ok ? '&#10004;' : (info.actual > 0 ? '&#10008;' : '&#9679;');
        html += `<li class="${cls}">
            <span class="icon ${cls}">${icon}</span>
            <span>${info.display_name}</span>
            <span class="count">${info.actual}/${info.required}</span>
        </li>`;
    }
    ul.innerHTML = html;
}

// ── OK/NG 오버레이 ─────────────────────────────────────

function showOk(s) {
    okShown = true;
    ngShown = false;
    stopSiren();
    document.getElementById('ng-overlay').classList.remove('active');
    document.getElementById('ok-overlay').classList.add('active');
    document.getElementById('ok-product-name').textContent = s.product_name || '';
    playChime();
    refreshTodayStats();
}

function showNg(s) {
    ngShown = true;
    okShown = false;
    document.getElementById('ok-overlay').classList.remove('active');
    document.getElementById('ng-overlay').classList.add('active');

    // 미달 항목 표시
    const list = document.getElementById('missing-list');
    list.innerHTML = '';
    if (s.missing_parts) {
        for (const mp of s.missing_parts) {
            const li = document.createElement('li');
            li.textContent = `${mp.face}면 - ${mp.display_name}: ${mp.actual}/${mp.required}`;
            list.appendChild(li);
        }
    }
    playSiren();
    refreshTodayStats();
}

function hideOverlays() {
    if (okShown) {
        document.getElementById('ok-overlay').classList.remove('active');
        okShown = false;
    }
    if (ngShown) {
        document.getElementById('ng-overlay').classList.remove('active');
        ngShown = false;
        stopSiren();
    }
}

function dismissNg() {
    document.getElementById('ng-overlay').classList.remove('active');
    ngShown = false;
    stopSiren();
    resetInspection();
}

// ── 컨트롤 ─────────────────────────────────────────────

async function startInspection() {
    await fetch('/api/start', { method: 'POST' });
}

async function resetInspection() {
    await fetch('/api/reset', { method: 'POST' });
    hideOverlays();
    stopSiren();
}

// ── 오늘 통계 ──────────────────────────────────────────

function resetTodayStats() {
    document.getElementById('reset-pw').value = '';
    document.getElementById('reset-modal').classList.add('active');
    document.getElementById('reset-pw').focus();
}

function closeResetModal() {
    document.getElementById('reset-modal').classList.remove('active');
}

async function confirmResetStats() {
    const pw = document.getElementById('reset-pw').value;
    if (pw !== '12345') { alert('비밀번호가 틀립니다'); return; }
    closeResetModal();
    await fetch('/api/stats/today', { method: 'DELETE' });
    refreshTodayStats();
}

async function refreshTodayStats() {
    try {
        const resp = await fetch('/api/stats/today');
        const s = await resp.json();
        document.getElementById('stat-total').textContent = s.total;
        document.getElementById('stat-ok').textContent = s.ok;
        document.getElementById('stat-ng').textContent = s.ng;
    } catch (e) {}
}

// ── 데모 뱃지 ──────────────────────────────────────────

async function checkDemo() {
    try {
        const resp = await fetch('/api/settings');
        const s = await resp.json();
        if (s.demo_mode === '1' || s.demo_mode === 'True') {
            document.getElementById('demo-badge').style.display = '';
        }
    } catch (e) {}
}

// ── 면 탭 클릭 ─────────────────────────────────────────

document.getElementById('tab-a').addEventListener('click', () => {
    activeFaceTab = 'A';
    document.getElementById('parts-a').style.display = '';
    document.getElementById('parts-b').style.display = 'none';
    document.getElementById('tab-a').classList.add('active');
    document.getElementById('tab-b').classList.remove('active');
});

document.getElementById('tab-b').addEventListener('click', () => {
    activeFaceTab = 'B';
    document.getElementById('parts-a').style.display = 'none';
    document.getElementById('parts-b').style.display = '';
    document.getElementById('tab-b').classList.add('active');
    document.getElementById('tab-a').classList.remove('active');
});

// ── 시작 ───────────────────────────────────────────────

pollStatus();
refreshTodayStats();
checkDemo();
setInterval(refreshTodayStats, 10000);
