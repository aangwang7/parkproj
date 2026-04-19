import os
import re
import json
import glob
import math
import numpy as np
import pandas as pd
import joblib
import urllib.parse
import urllib.request
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime
from research_loader import get_research_corpus
from dotenv import load_dotenv
from openai import OpenAI
import google.generativeai as genai

load_dotenv()

app = Flask(__name__, static_folder='.')
CORS(app)

# ── K2-THINK V2 ───────────────────────────────────────────
K2_API_KEY = os.environ.get("K2_API_KEY", "")
if K2_API_KEY:
    client = OpenAI(base_url="https://api.k2think.ai/v1", api_key=K2_API_KEY)
    print("[AI] K2-Think V2 ready via api.k2think.ai")
else:
    client = None
    print("[AI] WARNING: No K2_API_KEY — chat will return mock responses.")

# ── GEMINI (narrative summaries only) ────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-2.0-flash")
    print("[AI] Gemini ready for specialist narratives")
else:
    gemini_model = None
    print("[AI] WARNING: No GEMINI_API_KEY — specialist narrative disabled.")

# ── ML MODEL ──────────────────────────────────────────────
def load_model():
    if os.path.exists('pd_random_forest_model.pkl') and os.path.exists('standard_scaler.pkl'):
        return joblib.load('pd_random_forest_model.pkl'), joblib.load('standard_scaler.pkl')
    return None, None

model, scaler = load_model()

# ── PATIENT RECORDS SYSTEM ────────────────────────────────
RECORDS_DIR   = "patient_records"
RESULTS_DIR   = "patient_results"
REGISTRY_PATH = "patient_database.json"

for d in [RECORDS_DIR, RESULTS_DIR]:
    os.makedirs(d, exist_ok=True)

if os.path.exists(REGISTRY_PATH):
    with open(REGISTRY_PATH) as f:
        patient_registry = json.load(f)
    print(f"[DB] Loaded {len(patient_registry)} typing session(s)")
else:
    patient_registry = {}


def save_registry():
    with open(REGISTRY_PATH, 'w') as f:
        json.dump(patient_registry, f, indent=4)


def record_filename(name: str) -> str:
    slug = name.strip().lower().replace(' ', '_')
    return os.path.join(RECORDS_DIR, f"{slug}.json")


def load_record(name: str) -> dict | None:
    path = record_filename(name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)

    for filepath in glob.glob(os.path.join(RECORDS_DIR, "*.json")):
        try:
            with open(filepath) as f:
                rec = json.load(f)
            if name.lower() in rec.get('name', '').lower():
                return rec
        except Exception:
            continue

    return None


def save_record(record: dict):
    path = record_filename(record['name'])
    with open(path, 'w') as f:
        json.dump(record, f, indent=4)


def append_to_record(name: str, field: str, entry: dict) -> dict | None:
    record = load_record(name)
    if record is None:
        record = {
            "name": name.strip().title(),
            "demographics": {},
            "clinical_history": [],
            "risk_factors": [],
            "typing_sessions": [],
            "doctor_notes": []
        }

    if field not in record:
        record[field] = []

    record[field].append(entry)
    save_record(record)
    return record


def find_registry_key(name: str) -> str | None:
    name_lower = name.lower()
    if name_lower in patient_registry:
        return name_lower
    return next((k for k in patient_registry if name_lower in k), None)


# ── CORE RESEARCH ─────────────────────────────────────────
CORE_RESEARCH = """
=== NEUROQUERTY CORE RESEARCH ===

--- MIT-CS1PD (Giancardo et al., 2016, Scientific Reports) ---
HT-CV (coefficient of variation) is the primary biomarker (p=0.018).
Healthy HT mean ~0.12s, CV ~0.35 | Early PD HT mean ~0.17s, CV ~0.55. AUC ~0.73.

--- MIT-CS2PD (Adams et al., 2017) ---
Longitudinal HT variance increases over 6 months in PD patients. AUC improves to 0.81 with all 3 task types.

--- neuroQWERTY (Arroyo-Gallego et al., 2017, IEEE TBME) ---
Risk thresholds:
  Low:    HT-CV < 0.40, HT Mean < 0.15s, FT Std < 0.08s
  Medium: HT-CV 0.40-0.60 or HT Mean 0.15-0.22s
  High:   HT-CV > 0.60, HT Mean > 0.22s, FT Std > 0.12s
Sensitivity 72%, Specificity 74%.

--- BIOMARKER GUIDE ---
HT Mean: avg hold duration — elevated = bradykinesia
HT CV:   variability/mean — primary signal of motor control degradation
FT Std:  irregular flight times = motor timing deficit
Typing Speed: confounded by age and experience

--- CLINICAL CONTEXT ---
Screening tool only. High risk warrants neurological referral.
Gold standard: UPDRS. Imaging: DaTscan. Prodromal: REM disorder, hyposmia, constipation.
Risk factors: age >60, pesticide exposure, male sex, family history.
=== END CORE RESEARCH ===
"""

# ── FEATURE EXTRACTION ────────────────────────────────────
def extract_live_features(events):
    p_mouse = re.compile(r'mouse.+', re.IGNORECASE)
    p_meta  = re.compile(r'Shift|Alt|Control|Meta|Command', re.IGNORECASE)
    p_back  = re.compile(r'BackSpace', re.IGNORECASE)
    cleaned = []
    for ev in events:
        key = str(ev.get('key', ''))
        if p_mouse.match(key) or p_meta.match(key) or p_back.match(key):
            continue
        ht, press = ev.get('hold_time', 0), ev.get('press_time', 0)
        if 0 <= ht < 5 and press > 0:
            cleaned.append({'ht': ht, 'press': press})
    if len(cleaned) < 10:
        return None
    df         = pd.DataFrame(cleaned)
    ht_vals    = df['ht'].values
    press_vals = df['press'].values
    ft_vals    = np.diff(press_vals)
    ft_vals    = ft_vals[(ft_vals > 0) & (ft_vals < 5)]
    return {
        'ht_mean'     : float(np.mean(ht_vals)),
        'ht_std'      : float(np.std(ht_vals)),
        'ht_cv'       : float(np.std(ht_vals) / (np.mean(ht_vals) + 1e-9)),
        'ft_mean'     : float(np.mean(ft_vals)) if len(ft_vals) > 0 else 0.0,
        'ft_std'      : float(np.std(ft_vals))  if len(ft_vals) > 0 else 0.0,
        'typing_speed': float(len(ht_vals) / (press_vals[-1] - press_vals[0]) * 60) if len(press_vals) > 1 else 0.0
    }

FEAT_COLS = ['ht_mean', 'ht_std', 'ht_cv', 'ft_mean', 'ft_std', 'typing_speed']

def rule_based_probability(features):
    cv, ht, ft_s = features.get('ht_cv', 0), features.get('ht_mean', 0), features.get('ft_std', 0)
    score = 0.0
    if cv > 0.60:     score += 0.45
    elif cv > 0.40:   score += 0.20
    if ht > 0.22:     score += 0.30
    elif ht > 0.15:   score += 0.15
    if ft_s > 0.12:   score += 0.25
    elif ft_s > 0.08: score += 0.10
    return min(score, 0.95)


# ── SPECIALIST FINDER HELPERS ─────────────────────────────

NPI_TAXONOMIES = [
    ("Movement Disorders",      "Neurology – Movement Disorders"),
    ("Neurodegenerative",       "Neurology – Neurodegenerative Disorders"),
    ("Neurology",               "Neurology (general)"),
]

# Full US state name → 2-letter abbreviation lookup
STATE_ABBREVS = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}
ABBREV_SET = set(STATE_ABBREVS.values())


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles between two lat/lng points."""
    R    = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl   = math.radians(lon2 - lon1)
    a    = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def geocode_location(location: str) -> tuple[float, float] | None:
    """
    Convert a location string to (lat, lng) using Nominatim (OpenStreetMap).
    Completely free, no API key required.
    Nominatim usage policy: max 1 request/sec, no bulk geocoding — fine here.
    """
    url = (
        "https://nominatim.openstreetmap.org/search?"
        + urllib.parse.urlencode({
            "q"           : location,
            "format"      : "json",
            "limit"       : 1,
            "countrycodes": "us",
        })
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "neuroQWERTY-referral/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            results = json.loads(r.read())
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"[NOMINATIM] Geocoding error for '{location}': {e}")
    return None


def extract_city_state(location: str) -> tuple[str, str]:
    """
    Best-effort parse of 'City, ST', 'City, State', or 'City ST' → (city, state_abbrev).
    Falls back to (location, '') if unparseable.
    """
    parts = [p.strip() for p in location.replace(",", " ").split() if p.strip()]
    if not parts:
        return location, ""

    # Last token is already a 2-letter abbreviation
    if len(parts) >= 2 and parts[-1].upper() in ABBREV_SET:
        return " ".join(parts[:-1]), parts[-1].upper()

    # Last token(s) form a full state name
    loc_lower = location.lower()
    for full_name, abbrev in sorted(STATE_ABBREVS.items(), key=lambda x: -len(x[0])):
        if loc_lower.endswith(full_name):
            city = location[:len(location) - len(full_name)].strip(" ,")
            return city, abbrev

    return location, ""


def query_npi_registry(taxonomy_term: str, city: str, state: str, limit: int = 20) -> list[dict]:
    """
    Query the CMS NPPES NPI Registry API.
    - Completely free, no API key, no rate limits for reasonable use.
    - Returns verified licensed US healthcare providers only.
    - Docs: https://npiregistry.cms.hhs.gov/registry/help-api

    NOTE: taxonomy_description is a TEXT search field (substring match against the
    human-readable specialty description). Do NOT pass taxonomy codes here.
    """
    params: dict = {"version": "2.1", "limit": limit, "pretty": "false"}
    if taxonomy_term:
        params["taxonomy_description"] = taxonomy_term  # e.g. "Movement Disorders"
    if city:
        params["city"] = city
    if state:
        params["state"] = state

    url = "https://npiregistry.cms.hhs.gov/api/?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "neuroQWERTY-referral/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        return data.get("results", [])
    except Exception as e:
        print(f"[NPI] Query error (taxonomy={taxonomy_term}, city={city}, state={state}): {e}")
        return []


def parse_npi_provider(provider: dict, ref_lat: float, ref_lng: float) -> dict | None:
    """
    Flatten a raw NPI registry result into a clean specialist dict.
    Geocodes the provider's practice address via Nominatim to compute distance.
    Returns None if a usable name + address cannot be extracted.
    """
    basic = provider.get("basic", {})

    # Build display name
    if provider.get("enumeration_type") == "NPI-1":  # Individual
        first      = basic.get("first_name", "").strip().title()
        last       = basic.get("last_name", "").strip().title()
        credential = basic.get("credential", "").strip()
        name = f"Dr. {first} {last}".strip()
        if credential:
            name += f", {credential}"
    else:  # Organisation (NPI-2)
        name = basic.get("organization_name", "").strip()

    if not name or name in ("Dr. ", "Dr."):
        return None

    # Prefer practice/location address over mailing address
    addresses = provider.get("addresses", [])
    addr = next((a for a in addresses if a.get("address_purpose") == "LOCATION"), None)
    if addr is None and addresses:
        addr = addresses[0]
    if addr is None:
        return None

    street  = addr.get("address_1", "").strip()
    street2 = addr.get("address_2", "").strip()
    city    = addr.get("city", "").strip().title()
    state   = addr.get("state", "").strip().upper()
    zip_    = addr.get("postal_code", "")[:5]
    phone   = addr.get("telephone_number", "").strip()

    street_full  = f"{street} {street2}".strip() if street2 else street
    full_address = ", ".join(filter(None, [street_full, city, state, zip_]))

    if not full_address.strip(", "):
        return None

    # Geocode provider address for distance calculation
    distance = None
    if ref_lat and ref_lng and street and city and state:
        provider_coords = geocode_location(f"{street_full}, {city}, {state} {zip_}")
        if provider_coords:
            distance = round(haversine_miles(ref_lat, ref_lng, *provider_coords), 1)

    # Primary taxonomy → specialty label
    taxonomies  = provider.get("taxonomies", [])
    primary_tax = next((t for t in taxonomies if t.get("primary")), None)
    specialty   = primary_tax.get("desc", "Neurology") if primary_tax else "Neurology"

    npi_number = provider.get("number", "")

    # Deep-link to Google Maps search for this provider (no Maps key needed)
    maps_query = urllib.parse.quote_plus(f"{name} {city} {state}")
    maps_url   = f"https://www.google.com/maps/search/{maps_query}"

    return {
        "name"          : name,
        "npi"           : npi_number,
        "specialty"     : specialty,
        "address"       : full_address,
        "phone"         : phone or None,
        "distance_miles": distance,
        "maps_url"      : maps_url,
    }


# ── ROUTES ────────────────────────────────────────────────
@app.route('/')
def serve_patient():
    return send_from_directory('.', 'index.html')

@app.route('/patient')
def serve_patient():
    return send_from_directory('.', 'index.html')

@app.route('/doctor')
def serve_doctor():
    return send_from_directory('.', 'doctor.html')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('.', filename)

@app.route('/predict', methods=['POST'])
def predict():
    data = request.get_json()
    if not data or 'events' not in data:
        return jsonify({"error": "No events data provided"}), 400

    name   = data.get('patient_name', 'Anonymous').strip().title()
    events = data['events']

    features = extract_live_features(events)
    if features is None:
        return jsonify({"error": "Insufficient data (min 10 keystrokes required)"}), 400

    feature_vector = [features[k] for k in FEAT_COLS]

    if model and scaler:
        probability = float(model.predict_proba(scaler.transform([feature_vector]))[0][1])
        model_used  = "RandomForest"
    else:
        probability = rule_based_probability(features)
        model_used  = "RuleBased"

    risk = "High" if probability > 0.65 else "Medium" if probability > 0.35 else "Low"
    now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    session_entry = {
        "date"       : now,
        "risk"       : risk,
        "probability": round(probability, 4),
        "model_used" : model_used,
        "features"   : features
    }

    append_to_record(name, 'typing_sessions', session_entry)

    patient_registry[name.lower()] = {
        "name"       : name,
        "date"       : now,
        "risk"       : risk,
        "probability": probability,
        "model_used" : model_used,
        "features"   : features
    }
    save_registry()

    report = {"name": name, **session_entry, "raw_data": events}
    fname  = f"report_{name.replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(os.path.join(RESULTS_DIR, fname), 'w') as f:
        json.dump(report, f, indent=4)

    print(f"[PREDICT] {name} → {risk} ({probability:.3f}) | {model_used}")
    return jsonify({"classification": f"{risk} Risk", "probability": probability,
                    "risk": risk, "features": features, "model_used": model_used})


@app.route('/doctor/search', methods=['POST'])
def doctor_search():
    name = (request.json or {}).get('name', '').strip()
    if not name:
        return jsonify({"error": "No name provided"}), 400

    record       = load_record(name)
    registry_key = find_registry_key(name)
    biometrics   = patient_registry.get(registry_key, {}) if registry_key else {}

    if not record and not biometrics:
        return jsonify({"error": f"No record found for '{name}'. Have they completed the typing test?"}), 404

    history = {}
    if record:
        d = record.get('demographics', {})
        history = {
            "history": " | ".join(
                e['entry'] for e in record.get('clinical_history', [])
            ) or "No history on file.",
            "risk_factors": ", ".join(record.get('risk_factors', [])) or "None documented.",
            "demographics": d
        }

    if record and 'doctor_notes' in record:
        biometrics['doctor_notes'] = record['doctor_notes']

    if record and 'typing_sessions' in record:
        biometrics['typing_sessions'] = record['typing_sessions']

    return jsonify({"history": history, "biometrics": biometrics})


@app.route('/doctor/annotate', methods=['POST'])
def doctor_annotate():
    data  = request.json or {}
    name  = data.get('name', '').strip()
    text  = data.get('text', '').strip()
    atype = data.get('type', 'clinical').strip()

    if not name or not text:
        return jsonify({"error": "name and text are required"}), 400

    if atype not in {'clinical', 'followup', 'concern', 'clear'}:
        atype = 'clinical'

    annotation = {
        "type": atype,
        "text": text,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    updated_record = append_to_record(name, 'doctor_notes', annotation)

    registry_key = find_registry_key(name)
    if registry_key:
        patient_registry[registry_key]['doctor_notes'] = updated_record.get('doctor_notes', [])
        save_registry()

    print(f"[ANNOTATE] {name} ← {atype}: '{text[:60]}'")
    return jsonify({
        "success"     : True,
        "doctor_notes": updated_record.get('doctor_notes', [])
    })


@app.route('/doctor/chat', methods=['POST'])
def doctor_chat():
    data     = request.json or {}
    name     = data.get('name', '').strip()
    question = data.get('question', '').strip()
    history  = data.get('history', [])

    if not question:
        return jsonify({"error": "No question provided"}), 400

    record       = load_record(name) or {}
    registry_key = find_registry_key(name)
    biometrics   = patient_registry.get(registry_key, {}) if registry_key else {}
    demographics = record.get('demographics', {})
    features     = biometrics.get('features', {})

    sessions = record.get('typing_sessions', [])
    session_history_str = ""
    if sessions:
        session_history_str = "\nAll Typing Sessions (chronological):\n"
        for i, s in enumerate(sessions, 1):
            session_history_str += (
                f"  Session {i} ({s.get('date','?')}): {s.get('risk','?')} risk, "
                f"prob={s.get('probability','?')}, "
                f"HT-CV={s.get('features',{}).get('ht_cv','?')}, "
                f"HT-Mean={s.get('features',{}).get('ht_mean','?')}\n"
            )

    notes     = record.get('doctor_notes', [])
    notes_str = ""
    if notes:
        notes_str = "\nPhysician Annotations:\n"
        for n in notes:
            notes_str += f"  [{n.get('date','?')}] {n.get('type','?').upper()}: {n.get('text','')}\n"

    clin_history = record.get('clinical_history', [])
    clin_str = "\n".join(f"  {e.get('date','?')}: {e.get('entry','')}" for e in clin_history) or "Not on file."

    patient_ctx = f"""
=== PATIENT RECORD ===
Name:       {record.get('name', name)}
Age:        {demographics.get('age', 'Unknown')}
Sex:        {demographics.get('sex', 'Unknown')}
Ethnicity:  {demographics.get('ethnicity', 'Unknown')}
Occupation: {demographics.get('occupation', 'Unknown')}
Location:   {demographics.get('location', 'Unknown')}

Clinical History:
{clin_str}

Risk Factors:
{chr(10).join('  - ' + r for r in record.get('risk_factors', [])) or '  None documented.'}

=== LATEST TYPING TEST ===
Risk Classification: {biometrics.get('risk', 'Unknown')}
PD Probability:      {biometrics.get('probability', 'N/A')}
Model Used:          {biometrics.get('model_used', 'N/A')}
Date:                {biometrics.get('date', 'Unknown')}

Keystroke Biomarkers:
  Hold Time Mean (ht_mean):     {features.get('ht_mean', 'N/A')} s
  Hold Time Std Dev (ht_std):   {features.get('ht_std', 'N/A')} s
  Hold Time CV (ht_cv):         {features.get('ht_cv', 'N/A')}   ← primary PD signal
  Flight Time Mean (ft_mean):   {features.get('ft_mean', 'N/A')} s
  Flight Time Std Dev (ft_std): {features.get('ft_std', 'N/A')} s
  Typing Speed:                 {features.get('typing_speed', 'N/A')} keys/min
{session_history_str}{notes_str}"""

    pdf_corpus    = get_research_corpus()
    system_prompt = f"""You are a clinical decision-support assistant embedded in a physician's portal for Parkinson's disease screening via keystroke dynamics.

    STRICT OUTPUT FORMAT:
    - Exactly 3 sentences. No more.
    - Plain prose only. No headers, bullets, lists, markdown, or reasoning.
    - Sentence 1: State the risk level, PD probability, and the single most important biomarker value driving it.
    - Sentence 2: If only one session exists say so briefly; if multiple exist describe the trend. Include one additional biomarker value.
    - Sentence 3: One concrete next-step recommendation (neurology referral / UPDRS-III / DaTscan). Mention any relevant risk factor or annotation here.
    - Do NOT repeat biomarker values across sentences. Each value appears once only.
    - Do NOT show reasoning, thinking, or intermediate steps.
    - Write FINAL ANSWER: then immediately the 3 sentences with no line break in between.

{CORE_RESEARCH}

{pdf_corpus}

{patient_ctx}
"""

    if not client:
        return jsonify({"reply": (
            "[AI offline — K2_API_KEY not set]\n\n"
            f"Risk: {biometrics.get('risk','Unknown')} | Prob: {biometrics.get('probability','N/A')}\n"
            "Add your K2Think key to .env to enable AI reasoning."
        )})

    messages = [{"role": "system", "content": system_prompt}]
    for turn in history:
        if turn.get('role') in ('user', 'assistant') and turn.get('content'):
            messages.append({"role": turn['role'], "content": turn['content']})
    messages.append({"role": "user", "content": question})

    try:
        response = client.chat.completions.create(
            model="MBZUAI-IFM/K2-Think-v2",
            messages=messages,
            max_tokens=600,  # tight cap — 3 sentences need ~150 tokens; leaves room for reasoning
        )
        raw_reply = response.choices[0].message.content or ""

        # ── Strip K2-Think reasoning ──────────────────────────────────────
        # K2-Think V2 is a reasoning model. It emits its chain-of-thought as
        # plain prose (no tags), then outputs the final answer as a distinct
        # paragraph at the end. Strategy: try each extraction method in order,
        # fall back to the full reply if nothing matches.

        reply = raw_reply  # fallback

        # 1. Explicit FINAL ANSWER: delimiter (we instruct the model to use this)
        if 'FINAL ANSWER:' in raw_reply:
            reply = raw_reply.split('FINAL ANSWER:', 1)[-1].strip()

        # 2. <think>...</think> tags (some model versions / API configs use these)
        elif '<think>' in raw_reply:
            reply = re.sub(r'<think>.*?</think>', '', raw_reply, flags=re.DOTALL).strip()

        # 3. Explicit answer delimiter the model sometimes emits unprompted
        elif re.search(r'\n(final answer|answer)[:\s]*\n', raw_reply, re.IGNORECASE):
            parts = re.split(r'\n(?:final answer|answer)[:\s]*\n', raw_reply, flags=re.IGNORECASE)
            reply = parts[-1].strip()

        # 3. The reasoning ends with a blank line then the clean answer paragraph.
        #    Heuristic: the final paragraph (separated by \n\n) that looks like
        #    prose sentences (not a reasoning fragment starting with "We need",
        #    "Let's", "But", "However", "Maybe", "Check", "Thus", "So", "Now").
        else:
            reasoning_starters = re.compile(
                r"^(we |let'?s |but |however |maybe |check |thus |so |now |also |then |"
                r"since |given |because |this |that |the question|the instruction|"
                r"possible|better|alternatively|could|should|if |and |or )",
                re.IGNORECASE
            )
            paragraphs = [p.strip() for p in re.split(r'\n{2,}', raw_reply) if p.strip()]
            # Walk from the end; take the last paragraph that doesn't look like reasoning
            for para in reversed(paragraphs):
                first_line = para.split('\n')[0]
                if not reasoning_starters.match(first_line) and len(para) > 80:
                    reply = para
                    break

        # 4. Final clean-up: strip any leftover inline reasoning markers
        reply = re.sub(r'^(thinking|reasoning|thought process)[:\s]*', '',
                       reply, flags=re.IGNORECASE).strip()

        print(f"[K2] {name} — {len(raw_reply)} chars raw → {len(reply)} chars after strip")
        return jsonify({"reply": reply})
    except Exception as e:
        print(f"[K2 ERROR] {e}")
        return jsonify({"error": f"AI backend error: {str(e)}"}), 500


@app.route('/find_specialists', methods=['POST'])
def find_specialists():
    """
    Finds licensed Parkinson's neurologists and movement disorder specialists
    near the patient's location using two completely free, no-key-required services:

      1. Nominatim (OpenStreetMap) — geocodes the location string to lat/lng
      2. CMS NPPES NPI Registry    — official US government database of all
                                     licensed healthcare providers, filtered by
                                     specialty text search and city/state

    NPI taxonomy_description text terms queried (most specific → general):
      "Movement Disorders"   — Movement disorder sub-specialists
      "Neurodegenerative"    — Neurodegenerative disease specialists
      "Neurology"            — General neurologists (fallback)

    For small towns the search automatically broadens to state-wide with a
    relaxed radius so nearby-city specialists are not filtered out.

    Gemini (optional, free key) writes a clinical narrative summary.
    No paid API keys required anywhere in this pipeline.
    """
    data         = request.json or {}
    location     = data.get('location', '').strip()
    radius_miles = float(data.get('radius_miles', 50))

    if not location:
        return jsonify({"error": "No location provided"}), 400

    # ── Step 1: Geocode the patient's location via Nominatim ──────────
    coords = geocode_location(location)
    if coords is None:
        return jsonify({
            "error": (
                f"Could not geocode '{location}'. "
                "Try 'City, ST' format e.g. 'Princeton, NJ' or 'Chicago, IL'."
            )
        }), 400

    ref_lat, ref_lng = coords
    city, state = extract_city_state(location)

    print(f"[NPI] Searching near '{city}, {state}' ({ref_lat:.4f}, {ref_lng:.4f}), radius={radius_miles}mi")

    # ── Step 2: Query NPI Registry for each taxonomy term, deduplicate ──
    seen_npis     = set()
    raw_providers = []

    for taxonomy_term, taxonomy_label in NPI_TAXONOMIES:
        results = query_npi_registry(taxonomy_term, city, state, limit=20)
        print(f"[NPI] {taxonomy_label} (city={city or '*'}, state={state}): {len(results)} result(s)")
        for provider in results:
            npi_num = provider.get("number")
            if npi_num and npi_num not in seen_npis:
                seen_npis.add(npi_num)
                raw_providers.append(provider)

    # Fallback 1: broaden to state-wide if the city search returns nothing.
    # Small towns (e.g. Flemington NJ) often have zero providers listed under
    # that city in the NPI registry; specialists are in nearby larger cities.
    if not raw_providers and state:
        print(f"[NPI] No city results — retrying state-wide for {state}")
        for taxonomy_term, _ in NPI_TAXONOMIES[:2]:  # specialist terms only
            results = query_npi_registry(taxonomy_term, "", state, limit=25)
            for provider in results:
                npi_num = provider.get("number")
                if npi_num and npi_num not in seen_npis:
                    seen_npis.add(npi_num)
                    raw_providers.append(provider)

    if not raw_providers:
        return jsonify({
            "summary": (
                f"No licensed Parkinson's or movement disorder specialists found "
                f"in {location} via the NPI Registry. "
                f"Consider searching a nearby major city, or contact the "
                f"American Parkinson Disease Association (apdaparkinson.org) "
                f"for a regional referral directory."
            ),
            "specialists": [],
            "map_url": (
                "https://www.google.com/maps/search/"
                + urllib.parse.quote_plus(f"Parkinson neurologist near {location}")
            ),
            "source": "CMS NPPES NPI Registry (cms.gov)"
        })

    # ── Step 3: Parse providers, geocode addresses, filter by radius ──
    used_state_fallback = not any(
        p.get("addresses", [{}])[0].get("city", "").lower() == city.lower()
        for p in raw_providers
    ) if city else False
    effective_radius = max(radius_miles, 100.0) if used_state_fallback else radius_miles

    if used_state_fallback:
        print(f"[NPI] State-wide fallback active — relaxing radius to {effective_radius} mi")

    specialists = []
    for provider in raw_providers[:25]:
        parsed = parse_npi_provider(provider, ref_lat, ref_lng)
        if parsed is None:
            continue
        dist = parsed.get("distance_miles")
        if dist is not None and dist > effective_radius:
            continue
        specialists.append(parsed)

    # Sort: nearest first; providers whose address couldn't be geocoded go last
    specialists.sort(
        key=lambda x: (x.get("distance_miles") is None, x.get("distance_miles") or 999)
    )

    # ── Step 4: Gemini writes clinical referral narrative ─────────────
    summary = (
        f"Found {len(specialists)} licensed specialist(s) near {location} "
        f"via the CMS NPI Registry."
    )

    if gemini_model and specialists:
        try:
            names_block = "\n".join(
                "- {name} ({specialty}) — {address}{dist}".format(
                    name     = s["name"],
                    specialty= s.get("specialty", "Neurology"),
                    address  = s["address"],
                    dist     = f", {s['distance_miles']} mi away" if s.get("distance_miles") else ""
                )
                for s in specialists[:10]
            )
            narr_prompt = f"""You are a medical referral assistant helping a neurologist refer a patient \
with suspected Parkinson's disease.

The following licensed specialists were found near {location} via the US National Provider Identifier (NPI) Registry:

{names_block}

Write a concise 2-3 sentence clinical summary for the referring physician.
Mention the closest or most relevant specialist, distinguish movement disorder \
sub-specialists from general neurologists where possible, and include a brief \
practical recommendation (e.g. call ahead to confirm the provider sees Parkinson's patients, \
or check whether they are accepting new patients).
Do not invent any details not present in the list. Plain prose only — no bullet points, no headers."""

            narr = gemini_model.generate_content(narr_prompt)
            summary = narr.text.strip()
        except Exception as e:
            print(f"[GEMINI NARRATIVE] {e}")
            # summary stays as the factual fallback set above

    # ── Step 5: Google Maps search link (no key needed) ───────────────
    map_url = (
        "https://www.google.com/maps/search/"
        + urllib.parse.quote_plus(f"Parkinson neurologist near {location}")
    )

    print(f"[SPECIALISTS] Returning {len(specialists)} specialist(s) near {location}")
    return jsonify({
        "summary"    : summary,
        "specialists": specialists,
        "map_url"    : map_url,
        "source"     : "CMS NPPES NPI Registry (cms.gov) + Nominatim (openstreetmap.org)",
        "note"       : "All providers are US-licensed healthcare professionals verified by CMS.",
    })


@app.route('/health', methods=['GET'])
def health():
    records = len(glob.glob(os.path.join(RECORDS_DIR, "*.json")))
    return jsonify({
        "status"           : "healthy",
        "model_loaded"     : model is not None,
        "ai_ready"         : client is not None,
        "gemini_ready"     : gemini_model is not None,
        "specialist_finder": "CMS NPI Registry + Nominatim (no API key required)",
        "patient_records"  : records,
        "typing_sessions"  : len(patient_registry),
    })


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)