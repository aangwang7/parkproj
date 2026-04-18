// ── SPECIALIST FINDER ─────────────────────────────────────
// Talks to /find_specialists on the Flask backend.
// Backend calls Nominatim + CMS NPI Registry to find
// real Parkinson's neurologists near the patient's location.

const API_BASE_SPEC = window.location.origin;
let searchRadiusMiles = 5;

// ── TAB SWITCHING ─────────────────────────────────────────
function switchTab(tab, btn) {
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`tab-${tab}`).classList.add('active');
    btn.classList.add('active');
}

// ── RADIUS SELECTOR ───────────────────────────────────────
function setRadius(miles, btn) {
    searchRadiusMiles = miles;
    document.querySelectorAll('#tab-specialists .quick-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

// ── AUTO-FILL LOCATION FROM PATIENT RECORD ────────────────
// Called by doctor_logic.js after a patient is loaded
function autofillLocation(location) {
    const input = document.getElementById('location-input');
    if (input && location) {
        input.value = location;
    }
}

// ── FIND SPECIALISTS ──────────────────────────────────────
async function findSpecialists() {
    const location = document.getElementById('location-input').value.trim();
    if (!location) {
        alert('Please enter a location to search.');
        return;
    }

    const resultsEl = document.getElementById('specialist-results');
    resultsEl.innerHTML = `
        <div class="spec-loading">
            <div class="spinner"></div>
            Searching for Parkinson's specialists near <strong>${location}</strong>...
        </div>`;

    const mapLinkBar = document.getElementById('map-link-bar');
    if (mapLinkBar) mapLinkBar.style.display = 'none';

    try {
        const res  = await fetch(`${API_BASE_SPEC}/find_specialists`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ location, radius_miles: searchRadiusMiles })
        });
        const data = await res.json();

        if (data.error) {
            resultsEl.innerHTML = `<div style="color:var(--red);padding:20px;font-size:0.875rem;">⚠ ${data.error}</div>`;
            return;
        }

        renderSpecialists(data.specialists, data.summary, location, data.map_url);

    } catch (err) {
        resultsEl.innerHTML = `<div style="color:var(--red);padding:20px;font-size:0.875rem;">⚠ Could not reach the server. Is Flask running?</div>`;
    }
}

// ── RENDER RESULTS ────────────────────────────────────────
function renderSpecialists(specialists, summary, location, mapUrl) {
    const resultsEl  = document.getElementById('specialist-results');
    const mapLinkBar = document.getElementById('map-link-bar');
    const mapLink    = document.getElementById('map-external-link');

    // Show the "open in Google Maps" link instead of a blocked iframe
    if (mapUrl && mapLinkBar && mapLink) {
        mapLink.href           = mapUrl;
        mapLinkBar.style.display = 'block';
    }

    if (!specialists || specialists.length === 0) {
        resultsEl.innerHTML = `
            <div style="color:var(--text-muted);padding:20px;font-size:0.875rem;text-align:center;">
                No Parkinson's specialists found within ${searchRadiusMiles} miles of <strong>${location}</strong>.
                Try expanding the search radius.
            </div>`;
        return;
    }

    // Summary block (Gemini narrative or factual fallback)
    let html = '';
    if (summary) {
        html += `
            <div style="background:var(--accent-dim);border:1px solid rgba(56,189,248,0.2);border-radius:var(--radius);padding:14px;margin-bottom:16px;font-size:0.875rem;color:var(--text);line-height:1.6;">
                <div class="section-label" style="margin-bottom:6px;">Summary</div>
                ${formatReply(summary)}
            </div>`;
    }

    // Individual specialist cards
    specialists.forEach((spec, i) => {
        const rating   = spec.rating ? `<span class="rating-stars">${'★'.repeat(Math.round(spec.rating))}${'☆'.repeat(5 - Math.round(spec.rating))}</span> ${spec.rating}/5` : '';
        const mapsLink = spec.maps_url || `https://www.google.com/maps/search/${encodeURIComponent(spec.name + ' ' + location)}`;
        const phone    = spec.phone ? `<br>📞 ${spec.phone}` : '';
        const hours    = spec.open_now !== undefined
            ? `<br><span style="color:${spec.open_now ? 'var(--green)' : 'var(--red)'};">${spec.open_now ? '● Open now' : '● Closed'}</span>`
            : '';

        html += `
            <div class="specialist-card">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div class="specialist-name">${i + 1}. ${spec.name}</div>
                    ${spec.distance_miles != null ? `<span style="font-family:var(--font-mono);font-size:0.75rem;color:var(--text-muted);">${spec.distance_miles} mi</span>` : ''}
                </div>
                <div class="specialist-detail">
                    📍 ${spec.address || 'Address unavailable'}
                    ${phone}${hours}
                    ${rating ? `<br>${rating}` : ''}
                </div>
                ${spec.specialty ? `<span class="specialist-badge">🧠 ${spec.specialty}</span>` : ''}
                ${spec.summary ? `<div class="specialist-summary">${spec.summary}</div>` : ''}
                <a class="directions-btn" href="${mapsLink}" target="_blank" rel="noopener">
                    ↗ View on Google Maps
                </a>
            </div>`;
    });

    html += `<div class="gemini-attr">Results sourced from CMS NPPES NPI Registry (cms.gov) · Always verify contact details directly with the practice.</div>`;

    resultsEl.innerHTML = html;
}
