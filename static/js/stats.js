/**
 * 통계 페이지 로직
 * - 오늘 요약
 * - 일별 추이 바 차트 (Canvas 2D)
 * - 검사 이력 테이블
 */

let historyOffset = 0;
const PAGE_SIZE = 50;

// ── 오늘 요약 ──────────────────────────────────────────

async function loadTodayStats() {
    try {
        const resp = await fetch('/api/stats/today');
        const s = await resp.json();
        document.getElementById('s-total').textContent = s.total;
        document.getElementById('s-ok').textContent = s.ok;
        document.getElementById('s-ng').textContent = s.ng;
        document.getElementById('s-rate').textContent = s.ok_rate + '%';
    } catch (e) {}
}

// ── 차트 ───────────────────────────────────────────────

async function loadChart() {
    const start = document.getElementById('date-start').value;
    const end = document.getElementById('date-end').value;
    if (!start || !end) return;

    const resp = await fetch(`/api/stats/range?start_date=${start}&end_date=${end}`);
    const data = await resp.json();

    // 날짜별 집계
    const byDate = {};
    for (const row of data) {
        if (!byDate[row.date]) byDate[row.date] = { ok: 0, ng: 0 };
        byDate[row.date].ok += row.ok_count;
        byDate[row.date].ng += row.ng_count;
    }

    const dates = Object.keys(byDate).sort();
    const okData = dates.map(d => byDate[d].ok);
    const ngData = dates.map(d => byDate[d].ng);

    drawChart(dates, okData, ngData);
}

function drawChart(labels, okData, ngData) {
    const canvas = document.getElementById('chart');
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = 300 * dpr;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = '300px';
    ctx.scale(dpr, dpr);

    const W = rect.width;
    const H = 300;
    const pad = { top: 20, right: 20, bottom: 60, left: 50 };
    const chartW = W - pad.left - pad.right;
    const chartH = H - pad.top - pad.bottom;

    ctx.clearRect(0, 0, W, H);

    if (labels.length === 0) {
        ctx.fillStyle = '#666';
        ctx.font = '14px Malgun Gothic';
        ctx.textAlign = 'center';
        ctx.fillText('데이터가 없습니다', W / 2, H / 2);
        return;
    }

    const maxVal = Math.max(...okData, ...ngData, 1);
    const barW = Math.min(30, (chartW / labels.length - 6) / 2);

    // 그리드
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 5; i++) {
        const y = pad.top + chartH - (chartH * i / 5);
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(W - pad.right, y);
        ctx.stroke();

        ctx.fillStyle = '#666';
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText(Math.round(maxVal * i / 5), pad.left - 8, y + 4);
    }

    // 바 그리기
    for (let i = 0; i < labels.length; i++) {
        const x = pad.left + (i + 0.5) * (chartW / labels.length);

        // OK 바
        const okH = (okData[i] / maxVal) * chartH;
        ctx.fillStyle = '#4caf50';
        ctx.fillRect(x - barW - 1, pad.top + chartH - okH, barW, okH);

        // NG 바
        const ngH = (ngData[i] / maxVal) * chartH;
        ctx.fillStyle = '#f44336';
        ctx.fillRect(x + 1, pad.top + chartH - ngH, barW, ngH);

        // 날짜 레이블
        ctx.fillStyle = '#888';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        const dateStr = labels[i].substring(5); // MM-DD
        ctx.save();
        ctx.translate(x, pad.top + chartH + 15);
        ctx.rotate(-0.5);
        ctx.fillText(dateStr, 0, 0);
        ctx.restore();
    }

    // 범례
    const legY = H - 15;
    ctx.fillStyle = '#4caf50';
    ctx.fillRect(W / 2 - 80, legY - 8, 12, 12);
    ctx.fillStyle = '#aaa';
    ctx.font = '12px Malgun Gothic';
    ctx.textAlign = 'left';
    ctx.fillText('OK', W / 2 - 64, legY + 2);

    ctx.fillStyle = '#f44336';
    ctx.fillRect(W / 2 + 10, legY - 8, 12, 12);
    ctx.fillStyle = '#aaa';
    ctx.fillText('NG', W / 2 + 26, legY + 2);
}

// ── 검사 이력 ──────────────────────────────────────────

async function loadHistory(append) {
    if (!append) {
        historyOffset = 0;
        document.getElementById('hist-tbody').innerHTML = '';
    }

    const date = document.getElementById('hist-date').value || '';
    const result = document.getElementById('hist-result').value || '';

    let url = `/api/inspections?limit=${PAGE_SIZE}&offset=${historyOffset}`;
    if (date) url += `&date=${date}`;
    if (result) url += `&result=${result}`;

    const resp = await fetch(url);
    const rows = await resp.json();

    const tbody = document.getElementById('hist-tbody');
    for (const r of rows) {
        const tr = document.createElement('tr');
        const time = r.inspected_at ? r.inspected_at.split(' ')[1] || r.inspected_at : '-';
        const badge = r.result === 'OK'
            ? '<span class="badge badge-ok">OK</span>'
            : '<span class="badge badge-ng">NG</span>';

        let missing = '-';
        if (r.missing_parts) {
            try {
                const mp = JSON.parse(r.missing_parts);
                missing = mp.map(m => `${m.face}면-${m.display_name}(${m.actual}/${m.required})`).join(', ');
            } catch (e) { missing = r.missing_parts; }
        }

        let photos = '';
        if (r.a_face_photo) photos += `<a href="/api/inspections/${r.id}/photo/a" target="_blank">A</a> `;
        if (r.b_face_photo) photos += `<a href="/api/inspections/${r.id}/photo/b" target="_blank">B</a>`;
        if (!photos) photos = '-';

        const dur = r.duration_sec ? r.duration_sec.toFixed(1) + 's' : '-';

        tr.innerHTML = `<td>${time}</td><td>${r.product_name}</td><td>${badge}</td>
            <td>${dur}</td><td style="font-size:12px;">${missing}</td><td>${photos}</td>`;
        tbody.appendChild(tr);
    }

    historyOffset += rows.length;
    document.getElementById('load-more-btn').style.display =
        rows.length < PAGE_SIZE ? 'none' : '';
}

function loadMore() {
    loadHistory(true);
}

// ── 초기화 ─────────────────────────────────────────────

function init() {
    // 기본 날짜 설정
    const today = new Date();
    const end = today.toISOString().split('T')[0];
    const start = new Date(today.getTime() - 30 * 86400000).toISOString().split('T')[0];

    document.getElementById('date-start').value = start;
    document.getElementById('date-end').value = end;
    document.getElementById('hist-date').value = end;

    loadTodayStats();
    loadChart();
    loadHistory();
}

init();
