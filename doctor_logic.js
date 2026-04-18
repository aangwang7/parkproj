// ── CONFIG ────────────────────────────────────────────────
const API_BASE = window.location.origin;

// ── STATE ─────────────────────────────────────────────────
let currentPatient  = null;
let conversationHistory = [];

// ── SEARCH ────────────────────────────────────────────────
async function searchPatient() {
    const name  = document.getElementById('search-name').value.trim();
    if (!name) return;

    const panel = document.getElementById('patient-panel');
    panel.innerHTML = `<div style="color:var(--text-muted);font-size:0.875rem;padding:20px 0;">Searching...</div>`;

    try {
        const res = await fetch(`${API_BASE}/doctor/search`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });

        if (!res.ok) {
            panel.innerHTML = `<div style="color:var(--red);font-size:0.875rem;padding:20px 0;">
                ⚠ Patient not found. Either the name doesn't match or they haven't completed the typing test yet.
            </div>`;
            return;
        }

        const data     = await res.json();
        currentPatient = { name, ...data };
        renderPatientPanel(data);
        loadPatientContext(name, data);

        // Auto-fill location in specialist tab from patient record
        const loc = data.history?.demographics?.location || '';
        if (typeof autofillLocation === 'function') autofillLocation(loc);

    } catch (err) {
        panel.innerHTML = `<div style="color:var(--red);font-size:0.875rem;padding:20px 0;">⚠ Could not reach the server.</div>`;
    }
}

// ── RENDER PATIENT PANEL ──────────────────────────────────
function renderPatientPanel(data) {
    const b         = data.biometrics || {};
    const h         = data.history    || {};
    const f         = b.features      || {};
    const prob      = b.probability   ?? 0;
    const risk      = b.risk || (prob > 0.65 ? 'High' : prob > 0.35 ? 'Medium' : 'Low');
    const riskCls   = risk === 'High' ? 'risk-high' : risk === 'Medium' ? 'risk-medium' : 'risk-low';
    const fillColor = risk === 'High' ? 'var(--red)' : risk === 'Medium' ? 'var(--amber)' : 'var(--green)';
    const notes     = b.doctor_notes || [];

    document.getElementById('patient-panel').innerHTML = `
        <div class="section-label">Patient Record</div>
        <div class="patient-name">${currentPatient.name}</div>

        <div class="history-text">
            <strong style="color:var(--text-dim);display:block;margin-bottom:4px;">Clinical History</strong>
            ${h.history || 'No history on file.'}
            ${h.risk_factors ? `<br><br><strong style="color:var(--text-dim);">Risk Factors:</strong> ${h.risk_factors}` : ''}
        </div>

        <div class="risk-row">
            <div>
                <div class="section-label">PD Risk Classification</div>
                <span class="risk-badge ${riskCls}">${risk} Risk</span>
            </div>
            <div style="text-align:right;">
                <div class="section-label">Probability</div>
                <span style="font-family:var(--font-mono);font-size:1.1rem;color:var(--text);">${(prob*100).toFixed(1)}%</span>
            </div>
        </div>

        <div class="prob-track">
            <div class="prob-fill" id="prob-fill" style="width:0%;background:${fillColor};"></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:0.7rem;color:var(--text-muted);margin-bottom:16px;">
            <span>Low</span><span>Medium</span><span>High</span>
        </div>

        <div class="section-label">Keystroke Biomarkers</div>
        <div class="metrics-grid">
            <div class="metric-chip"><span class="val">${(f.ht_mean??0).toFixed(3)}s</span><span class="lbl">HT Mean</span></div>
            <div class="metric-chip"><span class="val">${(f.ht_cv??0).toFixed(3)}</span><span class="lbl">HT Variability</span></div>
            <div class="metric-chip"><span class="val">${Math.round(f.typing_speed??0)}</span><span class="lbl">Keys/min</span></div>
            <div class="metric-chip"><span class="val">${(f.ft_mean??0).toFixed(3)}s</span><span class="lbl">Flight Mean</span></div>
            <div class="metric-chip"><span class="val">${(f.ft_std??0).toFixed(3)}s</span><span class="lbl">Flight Std</span></div>
            <div class="metric-chip"><span class="val">${(f.ht_std??0).toFixed(3)}s</span><span class="lbl">HT Std Dev</span></div>
        </div>

        <!-- ── DOCTOR ANNOTATIONS ── -->
        <div style="margin-top:20px;">
            <div class="section-label">Physician Annotations</div>

            <!-- Existing notes -->
            <div id="notes-list" style="margin-bottom:12px;">
                ${renderNotes(notes)}
            </div>

            <!-- Add new annotation -->
            <div style="background:var(--bg-card-2);border:1px solid var(--border);border-radius:var(--radius);padding:14px;">
                <div style="font-size:0.8rem;color:var(--text-dim);margin-bottom:8px;font-weight:600;">Add Annotation</div>

                <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;">
                    <button class="flag-type-btn active" data-type="clinical" onclick="selectFlagType(this)">🩺 Clinical</button>
                    <button class="flag-type-btn" data-type="followup"  onclick="selectFlagType(this)">📅 Follow-up</button>
                    <button class="flag-type-btn" data-type="concern"   onclick="selectFlagType(this)">⚠ Concern</button>
                    <button class="flag-type-btn" data-type="clear"     onclick="selectFlagType(this)">✓ Cleared</button>
                </div>

                <textarea id="annotation-text"
                    style="width:100%;background:var(--bg-input);border:1px solid var(--border);border-radius:var(--radius);padding:10px;color:var(--text);font-family:var(--font-body);font-size:0.875rem;resize:none;height:80px;outline:none;box-sizing:border-box;"
                    placeholder="Write your clinical note here..."></textarea>

                <div style="display:flex;justify-content:flex-end;margin-top:10px;">
                    <button class="btn-main" onclick="saveAnnotation()" style="font-size:0.8rem;padding:8px 18px;">
                        Save to Record
                    </button>
                </div>
            </div>
        </div>
    `;

    // Animate probability bar
    setTimeout(() => {
        const fill = document.getElementById('prob-fill');
        if (fill) fill.style.width = `${Math.min(prob * 100, 100)}%`;
    }, 100);

    document.getElementById('quick-btns').style.display = 'flex';
}

// ── RENDER NOTES LIST ─────────────────────────────────────
function renderNotes(notes) {
    if (!notes || notes.length === 0) {
        return `<div style="color:var(--text-muted);font-size:0.82rem;font-style:italic;padding:6px 0;">No annotations yet.</div>`;
    }

    const typeStyles = {
        clinical: { icon: '🩺', color: 'var(--accent)',  bg: 'var(--accent-dim)' },
        followup: { icon: '📅', color: '#a78bfa',        bg: 'rgba(167,139,250,0.1)' },
        concern:  { icon: '⚠',  color: 'var(--amber)',   bg: 'var(--amber-dim)' },
        clear:    { icon: '✓',  color: 'var(--green)',   bg: 'var(--green-dim)' },
    };

    return notes.slice().reverse().map(n => {
        const s = typeStyles[n.type] || typeStyles.clinical;
        return `
            <div style="background:${s.bg};border-left:3px solid ${s.color};border-radius:var(--radius);padding:10px 12px;margin-bottom:8px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    <span style="font-size:0.75rem;font-weight:700;color:${s.color};text-transform:uppercase;letter-spacing:0.05em;">
                        ${s.icon} ${n.type}
                    </span>
                    <span style="font-size:0.7rem;color:var(--text-muted);font-family:var(--font-mono);">${n.date}</span>
                </div>
                <div style="font-size:0.875rem;color:var(--text);line-height:1.5;">${n.text}</div>
            </div>`;
    }).join('');
}

// ── FLAG TYPE SELECTOR ────────────────────────────────────
function selectFlagType(btn) {
    document.querySelectorAll('.flag-type-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

// ── SAVE ANNOTATION ───────────────────────────────────────
async function saveAnnotation() {
    const text = document.getElementById('annotation-text').value.trim();
    if (!text) {
        document.getElementById('annotation-text').style.borderColor = 'var(--red)';
        setTimeout(() => document.getElementById('annotation-text').style.borderColor = '', 1500);
        return;
    }

    const activeBtn = document.querySelector('.flag-type-btn.active');
    const type      = activeBtn ? activeBtn.dataset.type : 'clinical';

    try {
        const res  = await fetch(`${API_BASE}/doctor/annotate`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: currentPatient.name, type, text })
        });
        const data = await res.json();

        if (data.error) {
            appendMsg(`⚠ Could not save annotation: ${data.error}`, 'ai');
            return;
        }

        // Update local state and re-render notes list
        if (!currentPatient.biometrics) currentPatient.biometrics = {};
        currentPatient.biometrics.doctor_notes = data.doctor_notes;
        document.getElementById('notes-list').innerHTML = renderNotes(data.doctor_notes);
        document.getElementById('annotation-text').value = '';

        // Confirm in chat
        appendMsg(`✓ Annotation saved to <strong>${currentPatient.name}</strong>'s record: <em>${type} — "${text}"</em>`, 'ai');

    } catch (err) {
        appendMsg('⚠ Could not reach the server to save annotation.', 'ai');
    }
}

// ── LOAD CONTEXT INTO CHAT ────────────────────────────────
function loadPatientContext(name, data) {
    const chatWindow = document.getElementById('chat-window');
    chatWindow.innerHTML = '';
    conversationHistory = [];

    const b    = data.biometrics || {};
    const prob = b.probability ?? 0;
    const risk = b.risk || (prob > 0.65 ? 'High' : prob > 0.35 ? 'Medium' : 'Low');
    const notes = b.doctor_notes || [];

    let notesMsg = notes.length > 0
        ? `<br><br><strong>Existing annotations (${notes.length}):</strong> ${notes.map(n => `${n.type}: "${n.text}"`).join(' · ')}`
        : '';

    appendMsg(`Patient <strong>${name}</strong> loaded. Risk: <strong>${risk} (${(prob*100).toFixed(1)}%)</strong>.${notesMsg}<br><br>I have their full biometric profile and clinical history. What would you like to know?`, 'ai');
}

// ── CHAT ──────────────────────────────────────────────────
async function askAI() {
    const input    = document.getElementById('chat-input');
    const question = input.value.trim();
    if (!question) return;
    if (!currentPatient) { appendMsg('Please search for a patient first.', 'ai'); return; }

    appendMsg(question, 'dr');
    input.value = '';

    conversationHistory.push({ role: 'user', content: question });

    const thinkingId = appendThinking();

    try {
        const res  = await fetch(`${API_BASE}/doctor/chat`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name    : currentPatient.name,
                question,
                history : conversationHistory.slice(0, -1) // exclude the current turn (backend appends it)
            })
        });
        const data = await res.json();
        removeThinking(thinkingId);

        const reply = data.reply || data.error;
        appendMsg(formatReply(reply), 'ai');

        conversationHistory.push({ role: 'assistant', content: reply });

    } catch (err) {
        removeThinking(thinkingId);
        appendMsg('⚠ Could not reach the AI backend.', 'ai');
        // Remove the failed user turn from history so it can be retried cleanly
        conversationHistory.pop();
    }
}

function quickAsk(q) {
    document.getElementById('chat-input').value = q;
    askAI();
}

// ── HELPERS ───────────────────────────────────────────────
function appendMsg(text, type) {
    const win = document.getElementById('chat-window');
    const div = document.createElement('div');
    div.className = `msg ${type === 'ai' ? 'ai-msg' : 'dr-msg'}`;
    div.innerHTML = text;
    win.appendChild(div);
    win.scrollTop = win.scrollHeight;
    return div;
}

function appendThinking() {
    const win = document.getElementById('chat-window');
    const id  = 'thinking-' + Date.now();
    const div = document.createElement('div');
    div.id        = id;
    div.className = 'msg thinking-msg';
    div.innerHTML = `<span id="${id}-dots">K2 is reasoning</span>`;
    win.appendChild(div);
    win.scrollTop = win.scrollHeight;
    let dots = 0;
    div._interval = setInterval(() => {
        dots = (dots + 1) % 4;
        const el = document.getElementById(`${id}-dots`);
        if (el) el.textContent = 'K2 is reasoning' + '.'.repeat(dots);
    }, 400);
    return id;
}

function removeThinking(id) {
    const el = document.getElementById(id);
    if (el) { clearInterval(el._interval); el.remove(); }
}

function formatReply(text) {
    if (!text) return '(No response)';
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n\n/g, '<br><br>')
        .replace(/\n/g, '<br>');
}