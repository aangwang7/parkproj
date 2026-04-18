import os
import re
import numpy as np
import pandas as pd
import joblib
from flask import Flask, request, jsonify
from flask_cors import CORS  

app = Flask(__name__)
CORS(app) 


MODEL_PATH = 'pd_random_forest_model.pkl'
SCALER_PATH = 'standard_scaler.pkl'

def load_model():
    if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
        model = joblib.load(MODEL_PATH)
        scaler = joblib.load(SCALER_PATH)
        return model, scaler
    return None, None

model, scaler = load_model()


def extract_live_features(events):
    """
    Processes raw keypress events from the front-end.
    Filters: mouse clicks, modifiers (Shift/Alt/Ctrl), and backspaces.
    """
    # Regex patterns matching your research script
    p_mouse = re.compile(r'mouse.+', re.IGNORECASE)
    p_meta = re.compile(r'Shift|Alt|Control|Meta|Command', re.IGNORECASE)
    p_back = re.compile(r'BackSpace', re.IGNORECASE)

    cleaned_data = []
    for ev in events:
        key = str(ev.get('key', ''))
        
        # Apply the filters defined in your analysis
        if p_mouse.match(key) or p_meta.match(key) or p_back.match(key):
            continue
            
        ht = ev.get('hold_time', 0)
        press = ev.get('press_time', 0)
        
        # Valid data range based on research constraints
        if 0 <= ht < 5 and press > 0:
            cleaned_data.append({'ht': ht, 'press': press})

    if len(cleaned_data) < 10:
        return None

    df = pd.DataFrame(cleaned_data)
    ht_vals = df['ht'].values
    press_vals = df['press'].values
    
    # Calculate Flight Time (FT) - gap between consecutive presses
    ft_vals = np.diff(press_vals)
    ft_vals = ft_vals[(ft_vals > 0) & (ft_vals < 5)]

    # Feature engineering prioritized by your Random Forest results
    features = {
        'ht_mean': np.mean(ht_vals),
        'ht_std': np.std(ht_vals),
        'ht_cv': np.std(ht_vals) / (np.mean(ht_vals) + 1e-9),
        'ft_mean': np.mean(ft_vals) if len(ft_vals) > 0 else 0,
        'ft_std': np.std(ft_vals) if len(ft_vals) > 0 else 0,
        'typing_speed': len(ht_vals) / (press_vals[-1] - press_vals[0]) * 60 if len(press_vals) > 1 else 0
    }
    return features


@app.route('/predict', methods=['POST'])
def predict():
    data = request.get_json()
    if not data or 'events' not in data:
        return jsonify({"error": "No events data provided"}), 400

    features = extract_live_features(data['events'])
    
    if features is None:
        return jsonify({"error": "Insufficient valid keystrokes (min 10 required)"}), 400

    
    feature_vector = [
        features['ht_mean'], 
        features['ht_std'], 
        features['ht_cv'], 
        features['ft_mean'], 
        features['ft_std'], 
        features['typing_speed']
    ]

    response = {
        "features": features,
        "prediction_available": False,
        "message": "Features extracted successfully."
    }

    if model and scaler:
        scaled_features = scaler.transform([feature_vector])
        probability = model.predict_proba(scaled_features)[0][1]
        response["probability"] = float(probability)
        response["prediction_available"] = True
        response["classification"] = "High Risk" if probability > 0.5 else "Low Risk"

    return jsonify(response)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "model_loaded": model is not None})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)