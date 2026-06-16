/**
 * 메인 검사 화면 로직
 * - 브라우저 웹캠 → 서버 AI 추론 → 검출 박스 오버레이
 * - /api/status 폴링으로 검사 상태 실시간 갱신
 */

let prevState = 'idle';
let okShown = false;
let ngShown = false;
let activeFaceTab = 'A';
let latestDetections = [];
let isSending = false;

// ── 브라우저 웹캠 초기화 ──────────────────────────────

const video = document.getElementById('video-feed');
const overlayCanvas = document.getElementById('overlay-canvas');
const captureCanvas = document.getElementById('capture-canvas');
const overlayCtx = overlayCanvas.getContext('2d');
const captureCtx = captureCanvas.getContext('2d');

async function initCamera() {
    const statusEl = document.getElementById('camera-status');
    statusEl.textContent = '카메라 연결 중...';

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true });
        video.srcObject = stream;

        // 비디오 준비 대기
        await new Promise((resolve) => {
            if (video.readyState >= 1) { resolve(); return; }
            video.addEventListener('loadedmetadata', resolve, { once: true });
        });

        video.play();

        captureCanvas.width = video.videoWidth || 640;
        captureCanvas.height = video.videoHeight || 480;

        statusEl.textContent = '카메라 연결됨 (' + video.videoWidth + 'x' + video.videoHeight + ')';
        statusEl.style.color = '#4caf50';

        setInterval(sendFrame, 125);
        requestAnimationFrame(drawOverlay);
    } catch (e) {
        console.error('카메라 오류:', e);
        statusEl.textContent = '카메라 오류: ' + (e.message || e.name || '알 수 없음');
        statusEl.style.color = '#ff5722';
        fallbackToMjpeg();
    }
}

function fallbackToMjpeg() {
    const videoArea = video.parentElement;
    video.style.display = 'none';
    overlayCanvas.style.display = 'none';
    const img = document.createElement('img');
    img.id = 'video-feed-img';
    img.src = '/api/stream';
    img.style.cssText = 'width:100%;height:100%;object-fit:contain;';
    videoArea.appendChild(img);
}

// ── 프레임 전송 ───────────────────────────────────────

async function sendFrame() {
    if (isSending || video.readyState < 2 || !video.videoWidth) return;
    isSending = true;

    try {
        // 캔버스 크기 보정
        if (captureCanvas.width !== video.videoWidth) {
            captureCanvas.width = video.videoWidth;
            captureCanvas.height = video.videoHeight;
        }
        // 비디오 프레임 → 캔버스 → JPEG blob
        captureCtx.drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);
        const blob = await new Promise(resolve =>
            captureCanvas.toBlob(resolve, 'image/jpeg', 0.7)
        );
        if (!blob) { isSending = false; return; }

        const resp = await fetch('/api/frame', { method: 'POST', body: blob });
        const data = await resp.json();

        latestDetections = data.detections || [];
        updateUI(data.status);
    } catch (e) {
        // 네트워크 오류 무시
    }
    isSending = false;
}

// ── 검출 박스 오버레이 ────────────────────────────────

const DET_COLORS = {
    face_a: '#00ff00', face_b: '#ffa500',
    fastener: '#ff0000', clip: '#00c8ff',
    barcode: '#ffff00', protective_wrap: '#c800ff',
    black_pad: '#666666', insulate_pad: '#0096c8',
};

function drawOverlay() {
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    if (!vw || !vh) { requestAnimationFrame(drawOverlay); return; }

    // 캔버스 크기를 실제 표시 크기에 맞춤
    const rect = video.getBoundingClientRect();
    overlayCanvas.width = rect.width;
    overlayCanvas.height = rect.height;

    overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

    // 비디오→캔버스 좌표 변환 (object-fit: contain 대응)
    const videoAspect = vw / vh;
    const canvasAspect = rect.width / rect.height;
    let sx, sy, sw, sh;
    if (videoAspect > canvasAspect) {
        sw = rect.width;
        sh = rect.width / videoAspect;
        sx = 0;
        sy = (rect.height - sh) / 2;
    } else {
        sh = rect.height;
        sw = rect.height * videoAspect;
        sx = (rect.width - sw) / 2;
        sy = 0;
    }

    for (const det of latestDetections) {
        const [x1, y1, x2, y2] = det.bbox;
        const dx = sx + (x1 / vw) * sw;
        const dy = sy + (y1 / vh) * sh;
        const dw = ((x2 - x1) / vw) * sw;
        const dh = ((y2 - y1) / vh) * sh;

        const color = DET_COLORS[det.class_name] || '#ccc';
        overlayCtx.strokeStyle = color;
        overlayCtx.lineWidth = 2;
        overlayCtx.strokeRect(dx, dy, dw, dh);

        const label = `${det.class_name} ${Math.round(det.confidence * 100)}%`;
        overlayCtx.font = '13px sans-serif';
        overlayCtx.fillStyle = color;
        overlayCtx.fillText(label, dx, dy - 4);
    }

    requestAnimationFrame(drawOverlay);
}

// ── 상태 폴링 (프레임 전송 없을 때 보조) ──────────────

async function pollStatus() {
    try {
        const resp = await fetch('/api/status');
        const s = await resp.json();
        updateUI(s);
    } catch (e) {
        document.getElementById('camera-status').textContent = '연결 끊김';
    }
    setTimeout(pollStatus, 500);
}

function updateUI(s) {
    if (!s) return;
    const state = s.state;

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

    // 버튼 전환
    const btnStart = document.getElementById('btn-start');
    const btnReset = document.getElementById('btn-reset');
    if (state === 'standby') {
        btnStart.style.display = '';
        btnReset.style.display = 'none';
    } else {
        btnStart.style.display = 'none';
        btnReset.style.display = '';
    }

    // 경과 시간
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

initCamera();
pollStatus();
refreshTodayStats();
setInterval(refreshTodayStats, 10000);
