import os
import re
import numpy as np
import pandas as pd
import joblib  # Added for exporting the model
from scipy import stats
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
import warnings
warnings.filterwarnings('ignore')


def load_keypress_csv(filepath):
    # Standard neuroQWERTY filters: No mouse, no modifiers, no backspace
    pMouse    = re.compile(r'"mouse.+"')
    pLongMeta = re.compile(r'"Shift.+"|"Alt.+"|"Control.+"')
    pBack     = re.compile(r'"BackSpace"')
 
    try:
        df = pd.read_csv(filepath, header=None, names=['key', 'ht', 'release', 'press'])
        mask = ~(df['key'].str.match(pMouse) | df['key'].str.match(pLongMeta) | df['key'].str.match(pBack))
        df = df[mask].copy()
        # Ensure timings are realistic for motor control analysis
        df = df[(df['ht'] >= 0) & (df['ht'] < 5) & (df['press'] > 0)]
        return df.reset_index(drop=True)
    except Exception:
        return None

def extract_features(df):
    if df is None or len(df) < 10:
        return {}
 
    ht    = df['ht'].values
    press = df['press'].values
    ft    = np.diff(press)
    ft    = ft[(ft > 0) & (ft < 5)]
 
    return {
        'ht_mean'     : np.mean(ht),
        'ht_std'      : np.std(ht),
        'ht_cv'       : np.std(ht) / (np.mean(ht) + 1e-9), # Variance is key for PD
        'ft_mean'     : np.mean(ft) if len(ft) > 0 else 0,
        'ft_std'      : np.std(ft)  if len(ft) > 0 else 0,
        'typing_speed': len(ht) / (press[-1] - press[0]) * 60 if press[-1] > press[0] else 0,
    }

FEAT_COLS = ['ht_mean', 'ht_std', 'ht_cv', 'ft_mean', 'ft_std', 'typing_speed']

def train_and_export_model(gt_csv, data_dir):
    print(f"Processing {gt_csv}...")
    gt = pd.read_csv(gt_csv).set_index('pID')
    rows = []
    
    for pid, row in gt.iterrows():
        # Check both file_1 and file_2 as per MIT-CS1PD structure
        for col in ['file_1', 'file_2']:
            if col in row and pd.notna(row[col]):
                df = load_keypress_csv(os.path.join(data_dir, str(row[col])))
                feats = extract_features(df)
                if feats:
                    feats['gt_bin'] = 1 if row['gt'] == True else 0
                    rows.append(feats)

    agg = pd.DataFrame(rows)
    X = agg[FEAT_COLS].fillna(agg[FEAT_COLS].median())
    y = agg['gt_bin']

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    rf = RandomForestClassifier(n_estimators=300, max_depth=4, random_state=42)
    rf.fit(X_scaled, y)

    joblib.dump(rf, 'pd_random_forest_model.pkl')
    joblib.dump(scaler, 'standard_scaler.pkl')
    
    print("\n✅ Model and Scaler exported successfully.")
    print(f"Features used: {FEAT_COLS}")
    return rf


if __name__ == '__main__':
    CS1PD_GT = "MIT-CS1PD/GT_DataPD_MIT-CS1PD.csv"
    CS1PD_DIR = "MIT-CS1PD/data_MIT-CS1PD/"
    
    if os.path.exists(CS1PD_GT):
        train_and_export_model(CS1PD_GT, CS1PD_DIR)
    else:
        print("Error: Could not find dataset. Check folder structure.")