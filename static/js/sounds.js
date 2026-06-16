/**
 * Web Audio API 사운드 시스템
 * OK: 띵동 (C5+E5 화음)
 * NG: 크고 귀아픈 사이렌 (800↔1200Hz 반복)
 */

let audioCtx = null;
let sirenNodes = null;

function ensureAudioCtx() {
    if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtx.state === 'suspended') {
        audioCtx.resume();
    }
    return audioCtx;
}

// 사용자 인터랙션으로 AudioContext 활성화
document.addEventListener('click', () => ensureAudioCtx(), { once: true });

function playChime() {
    const ctx = ensureAudioCtx();
    const now = ctx.currentTime;

    // 첫 번째 음 (C5 = 523Hz)
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = 'sine';
    osc1.frequency.value = 523.25;
    gain1.gain.setValueAtTime(0, now);
    gain1.gain.linearRampToValueAtTime(0.4, now + 0.02);
    gain1.gain.exponentialRampToValueAtTime(0.01, now + 0.6);
    osc1.connect(gain1).connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.6);

    // 두 번째 음 (E5 = 659Hz) - 약간 딜레이
    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = 'sine';
    osc2.frequency.value = 659.25;
    gain2.gain.setValueAtTime(0, now + 0.1);
    gain2.gain.linearRampToValueAtTime(0.4, now + 0.12);
    gain2.gain.exponentialRampToValueAtTime(0.01, now + 0.8);
    osc2.connect(gain2).connect(ctx.destination);
    osc2.start(now + 0.1);
    osc2.stop(now + 0.8);

    // 세 번째 음 (G5 = 784Hz) - 화음 완성
    const osc3 = ctx.createOscillator();
    const gain3 = ctx.createGain();
    osc3.type = 'sine';
    osc3.frequency.value = 783.99;
    gain3.gain.setValueAtTime(0, now + 0.2);
    gain3.gain.linearRampToValueAtTime(0.3, now + 0.22);
    gain3.gain.exponentialRampToValueAtTime(0.01, now + 1.0);
    osc3.connect(gain3).connect(ctx.destination);
    osc3.start(now + 0.2);
    osc3.stop(now + 1.0);
}

function playSiren() {
    if (sirenNodes) return; // 이미 재생 중

    const ctx = ensureAudioCtx();
    const now = ctx.currentTime;

    // 메인 사이렌 오실레이터
    const osc = ctx.createOscillator();
    osc.type = 'sawtooth';
    // 800Hz ↔ 1200Hz 교대 (0.4초 주기)
    osc.frequency.setValueAtTime(800, now);
    for (let i = 0; i < 60; i++) {
        const t = now + i * 0.4;
        osc.frequency.setValueAtTime(i % 2 === 0 ? 800 : 1200, t);
    }

    // 게인 (크게)
    const gain = ctx.createGain();
    gain.gain.value = 0.6;

    // 디스토션으로 더 귀아프게
    const distortion = ctx.createWaveShaper();
    const curve = new Float32Array(256);
    for (let i = 0; i < 256; i++) {
        const x = (i * 2) / 256 - 1;
        curve[i] = Math.sign(x) * Math.pow(Math.abs(x), 0.5);
    }
    distortion.curve = curve;

    osc.connect(distortion).connect(gain).connect(ctx.destination);
    osc.start(now);

    sirenNodes = { osc, gain, distortion };
}

function stopSiren() {
    if (!sirenNodes) return;
    try {
        sirenNodes.osc.stop();
        sirenNodes.osc.disconnect();
        sirenNodes.gain.disconnect();
        sirenNodes.distortion.disconnect();
    } catch (e) {}
    sirenNodes = null;
}
