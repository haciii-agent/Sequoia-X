"""全市场ML训练脚本 - 跳过CV直接训练。"""
import sys, os
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
os.chdir("D:/hermes/seq-tmp")

print("[1/3] 加载数据...", flush=True)
from sequoia_x.core.config import get_settings
from sequoia_x.data.engine import DataEngine
from sequoia_x.analysis.ml_predictor import MLPredictor

settings = get_settings()
engine = DataEngine(settings)
symbols = engine.get_local_symbols()
print(f"共 {len(symbols)} 只股票", flush=True)

all_data = []
for i, code in enumerate(symbols):
    try:
        df = engine.get_ohlcv(code)
        if df is not None and len(df) >= 80:
            all_data.append(df)
    except:
        pass
    if (i + 1) % 1000 == 0:
        print(f"  已加载 {i + 1}/{len(symbols)}，有效 {len(all_data)}...", flush=True)

print(f"[1/3] 数据加载完成: {len(all_data)} 只有效股票", flush=True)

print("[2/3] 特征工程...", flush=True)
import numpy as np
import pandas as pd
import joblib, hashlib, time
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sequoia_x.analysis.ml_predictor import build_features, build_labels, MODEL_DIR, CACHE_DIR

# 检查缓存
cache_key = hashlib.md5(f"stocks{len(all_data)}_rows{sum(len(d) for d in all_data)}_fwd3_thr0.03".encode()).hexdigest()[:12]
cache_path = os.path.join(CACHE_DIR, f"{cache_key}.pkl")

if os.path.exists(cache_path):
    print("[2/3] 发现缓存，直接加载...", flush=True)
    cached = joblib.load(cache_path)
    X_all, y_all, feature_names = cached["X"], cached["y"], cached["feature_names"]
else:
    print("[2/3] 并行计算特征...", flush=True)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from sequoia_x.analysis.ml_predictor import _process_single_stock

    args_list = [(df["code"].iloc[0] if "code" in df.columns else "unknown", df.to_dict(orient="list"), 3, 0.03) for df in all_data]
    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_process_single_stock, a): a[0] for a in args_list}
        for future in as_completed(futures):
            r = future.result()
            if r is not None:
                results.append(r)
            if len(results) % 100 == 0 and len(results) > 0:
                print(f"  特征处理: {len(results)} 只完成 ({time.time()-t0:.0f}s)", flush=True)

    feature_names = results[0]["feature_names"]
    X_all, y_all = [], []
    for r in results:
        X_all.extend(r["X"])
        y_all.extend(r["y"])
    X_all, y_all = np.array(X_all), np.array(y_all)

    os.makedirs(CACHE_DIR, exist_ok=True)
    joblib.dump({"X": X_all, "y": y_all, "feature_names": feature_names}, cache_path)
    print(f"[2/3] 特征缓存已保存", flush=True)

print(f"[2/3] 训练集: {len(X_all)} 条，正样本: {np.mean(y_all):.2%}", flush=True)

print("[3/3] 训练模型...", flush=True)
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X_all)

model = GradientBoostingClassifier(
    n_estimators=200, max_depth=5, learning_rate=0.1,
    subsample=0.8, min_samples_leaf=50, random_state=42,
)
model.fit(X_scaled, y_all)
print("[3/3] 训练完成！", flush=True)

# 特征重要性
importances = pd.Series(model.feature_importances_, index=feature_names)
top10 = importances.nlargest(10)
print("\n特征重要性 TOP10:", flush=True)
for feat, imp in top10.items():
    print(f"  {feat}: {imp:.4f}", flush=True)

# 保存
os.makedirs(MODEL_DIR, exist_ok=True)
joblib.dump(model, os.path.join(MODEL_DIR, "gbm_model.pkl"))
joblib.dump(scaler, os.path.join(MODEL_DIR, "scaler.pkl"))
joblib.dump(feature_names, os.path.join(MODEL_DIR, "feature_names.pkl"))
print(f"\n模型已保存到 {MODEL_DIR}", flush=True)
print("DONE", flush=True)
