// ── CONFIG ────────────────────────────────────────────────
const API_BASE = window.location.origin;

// ── TASKS ─────────────────────────────────────────────────
const taskSequence = [
    { id: 'repetitive', label: 'Repetitive Text',    text: 'aaaaa jjjjj rrrrr ppppp',                           hint: 'Type the characters above exactly as shown.' },
    { id: 'standard',   label: 'Standard Text',      text: 'The quick brown fox jumps over the lazy dog.',      hint: 'Type the sentence above exactly as shown.' },
    { id: 'natural',    label: 'Natural Text',       text: 'Tell us about what you ate for breakfast today.',   hint: 'Type your response freely, then press Enter when done.' }
];

// ── STATE ─────────────────────────────────────────────────
let currentStep = 0;
let startTime   = null;
let keyLog      = [];
let allEvents   = [];
let activeKeys  = {};

// ── DOM ───────────────────────────────────────────────────
const taskLabel   = document.getElementById('task-label');
const targetText  = document.getElementById('target-text');
const inputField  = document.getElementById('input-field');
const stepDisplay = document.getElementById('current-step');
const progressBar = document.getElementById('progress-bar');
const statusEl    = document.getElementById('status-container');
const typingArea  = document.getElementById('typing-area');

// ── PASTE / AUTOFILL BLOCKING ─────────────────────────────
// Silently block — no logging, no flags, just prevent it.

function flashWarning(msg) {
    statusEl.style.color = 'var(--amber)';
    statusEl.innerText   = '⚠ ' + msg;
    setTimeout(() => {
        statusEl.style.color = '';
        statusEl.innerText   = taskSequence[currentStep]?.hint || '';
    }, 2500);
}

inputField.addEventListener('paste', (e) => {
    e.preventDefault();
    flashWarning('Pasting is not allowed. Please type manually.');
});

inputField.addEventListener('drop', (e) => {
    e.preventDefault();
    flashWarning('Please type the text manually.');
});

// Catch browser autofill: if the field suddenly has a lot of text
// without any keyLog entries this tick, wipe it.
inputField.addEventListener('input', () => {
    if (inputField.value.length > keyLog.length + 4 && keyLog.length === 0) {
        inputField.value = '';
        flashWarning('Auto-fill is not allowed. Please type manually.');
    }
});

// ── INIT ──────────────────────────────────────────────────
function initTask(index) {
    const task = taskSequence[index];
    taskLabel.innerText     = task.label;
    targetText.innerText    = task.text;
    stepDisplay.innerText   = index + 1;
    progressBar.style.width = `${(index / taskSequence.length) * 100}%`;

    inputField.value     = '';
    inputField.disabled  = false;
    inputField.focus();
    keyLog     = [];
    startTime  = null;
    activeKeys = {};
    statusEl.style.color = '';
    statusEl.innerText   = task.hint;
}

// ── KEYSTROKE CAPTURE ─────────────────────────────────────
inputField.addEventListener('keydown', (e) => {
    // Block Ctrl/Cmd+V and Ctrl/Cmd+X silently
    if ((e.ctrlKey || e.metaKey) && (e.key === 'v' || e.key === 'x')) {
        e.preventDefault();
        flashWarning('Pasting is not allowed. Please type manually.');
        return;
    }

    if (!startTime) startTime = performance.now();
    if (activeKeys[e.code]) return;

    activeKeys[e.code] = {
        key: e.key,
        pressTime: (performance.now() - startTime) / 1000
    };
});

inputField.addEventListener('keyup', (e) => {
    if (!activeKeys[e.code]) return;

    const releaseTime  = (performance.now() - startTime) / 1000;
    const holdDuration = releaseTime - activeKeys[e.code].pressTime;

    keyLog.push({
        task:         taskSequence[currentStep].id,
        key:          e.key,
        hold_time:    holdDuration,
        press_time:   activeKeys[e.code].pressTime,
        release_time: releaseTime
    });

    delete activeKeys[e.code];

    if (currentStep < 2) {
        if (inputField.value.length >= targetText.innerText.length) completeTask();
    } else {
        statusEl.innerText = "Press Enter when you're done.";
        if (e.key === 'Enter') completeTask();
    }
});

// ── TASK COMPLETE ─────────────────────────────────────────
function completeTask() {
    inputField.disabled = true;
    allEvents = allEvents.concat(keyLog);

    currentStep++;
    if (currentStep < taskSequence.length) {
        statusEl.innerText = '✓ Task complete. Loading next...';
        setTimeout(() => initTask(currentStep), 800);
    } else {
        progressBar.style.width = '100%';
        showAnalysis();
    }
}

// ── SUBMIT & SHOW ANALYSIS ────────────────────────────────
async function showAnalysis() {
    const patientName = localStorage.getItem('nq_patient_name') || 'Anonymous';

    typingArea.innerHTML = `
        <div style="padding: 20px 0;">
            <div class="section-label">Analyzing your session</div>
            <div style="margin-top: 20px;" id="steps-container"></div>
        </div>
    `;

    const steps = ['Filtering keystroke noise', 'Computing hold-time variability',
                   'Calculating flight-time metrics', 'Running motor control classifier',
                   'Generating clinical summary'];

    const container = document.getElementById('steps-container');
    for (let i = 0; i < steps.length; i++) {
        await delay(600);
        const el = document.createElement('div');
        el.style.cssText = `display:flex;align-items:center;gap:12px;padding:8px 0;font-size:0.9rem;color:var(--text-muted);opacity:0;transition:opacity 0.3s;`;
        el.innerHTML     = `<span style="color:var(--accent);">◦</span> ${steps[i]}...`;
        container.appendChild(el);
        requestAnimationFrame(() => el.style.opacity = '1');
    }

    try {
        const res  = await fetch(`${API_BASE}/predict`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ patient_name: patientName, events: allEvents })
        });
        const data = await res.json();
        showResult(data);
    } catch (err) {
        typingArea.innerHTML = `
            <div style="text-align:center;padding:40px 20px;">
                <div style="color:var(--red);margin-bottom:8px;">⚠ Could not reach analysis server.</div>
                <div style="color:var(--text-muted);font-size:0.85rem;">Make sure the Flask backend is running.</div>
            </div>`;
    }
}

function showResult(data) {
    const prob    = data.probability ?? 0;
    const risk    = prob > 0.65 ? 'High' : prob > 0.35 ? 'Medium' : 'Low';
    const riskCls = risk === 'High' ? 'risk-high' : risk === 'Medium' ? 'risk-medium' : 'risk-low';
    const f       = data.features || {};

    typingArea.innerHTML = `
        <div style="padding:10px 0;">
            <div class="section-label">Session Complete</div>
            <div style="margin:12px 0 6px;"><span class="risk-badge ${riskCls}">${risk} Risk</span></div>
            <div style="color:var(--text-muted);font-size:0.85rem;margin-bottom:20px;line-height:1.5;"> Results saved for physician review.
            </div>
            <div style="margin-top:20px;padding:14px;background:var(--bg-card-2);border:1px solid var(--border);border-radius:var(--radius);font-size:0.8rem;color:var(--text-muted);line-height:1.6;">
                ℹ This tool is for screening purposes only. Your physician will review these results and make a decision accordingly.
            </div>
        </div>`;
}

function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── START ─────────────────────────────────────────────────
const name = prompt('Please enter your full name for the session record:');
if (name && name.trim()) localStorage.setItem('nq_patient_name', name.trim());
initTask(0);