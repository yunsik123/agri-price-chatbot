"""
로컬 XGBoost 시계열 예측 + S3 업로드
"""

import pandas as pd
import numpy as np
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error
import boto3
import os
from datetime import datetime
from io import StringIO

# 설정
REGION = 'ap-southeast-2'
BUCKET_NAME = 'agri-sagemaker-data-260893304786'
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, 'data', 'sample_agri_prices.csv')
OUTPUT_PATH = os.path.join(BASE_DIR, 'data', 'forecast_results.csv')

s3 = boto3.client('s3', region_name=REGION)


def parse_period(period_str):
    year = int(period_str[:4])
    month = int(period_str[4:6])
    if '상순' in period_str:
        day = 5
    elif '중순' in period_str:
        day = 15
    else:
        day = 25
    return datetime(year, month, day)


def create_features(df):
    df = df.copy()
    df['date'] = df['period_raw'].apply(parse_period)
    df = df.sort_values('date')

    df['year'] = df['date'].dt.year
    df['month'] = df['date'].dt.month
    df['day_of_year'] = df['date'].dt.dayofyear
    df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
    df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)

    for lag in [1, 2, 3, 6, 9, 12]:
        df[f'lag_{lag}'] = df['price_kg'].shift(lag)

    df['ma_3'] = df['price_kg'].rolling(3).mean()
    df['ma_6'] = df['price_kg'].rolling(6).mean()
    df['ma_12'] = df['price_kg'].rolling(12).mean()
    df['std_6'] = df['price_kg'].rolling(6).std()

    return df


def train_and_forecast(item_df, forecast_periods=9):
    df = create_features(item_df)

    feature_cols = ['year', 'month', 'day_of_year', 'month_sin', 'month_cos',
                    'lag_1', 'lag_2', 'lag_3', 'lag_6', 'lag_9', 'lag_12',
                    'ma_3', 'ma_6', 'ma_12', 'std_6']

    df_clean = df.dropna(subset=feature_cols + ['price_kg'])

    if len(df_clean) < 20:
        return None, None

    X = df_clean[feature_cols]
    y = df_clean['price_kg']

    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    model = XGBRegressor(
        n_estimators=100, max_depth=5, learning_rate=0.1,
        subsample=0.8, colsample_bytree=0.8, random_state=42, verbosity=0
    )
    model.fit(X_train, y_train)

    mae = mean_absolute_error(y_test, model.predict(X_test))

    # 미래 예측
    last_row = df_clean.iloc[-1]
    last_date = last_row['date']
    price_history = df_clean['price_kg'].tolist()

    forecasts = []
    for i in range(1, forecast_periods + 1):
        future_date = last_date + pd.Timedelta(days=10 * i)

        features = {
            'year': future_date.year,
            'month': future_date.month,
            'day_of_year': future_date.dayofyear,
            'month_sin': np.sin(2 * np.pi * future_date.month / 12),
            'month_cos': np.cos(2 * np.pi * future_date.month / 12),
            'lag_1': price_history[-1],
            'lag_2': price_history[-2] if len(price_history) >= 2 else price_history[-1],
            'lag_3': price_history[-3] if len(price_history) >= 3 else price_history[-1],
            'lag_6': price_history[-6] if len(price_history) >= 6 else price_history[-1],
            'lag_9': price_history[-9] if len(price_history) >= 9 else price_history[-1],
            'lag_12': price_history[-12] if len(price_history) >= 12 else price_history[-1],
            'ma_3': np.mean(price_history[-3:]),
            'ma_6': np.mean(price_history[-6:]) if len(price_history) >= 6 else np.mean(price_history[-3:]),
            'ma_12': np.mean(price_history[-12:]) if len(price_history) >= 12 else np.mean(price_history[-6:]),
            'std_6': np.std(price_history[-6:]) if len(price_history) >= 6 else 0,
        }

        pred = max(model.predict(pd.DataFrame([features]))[0], 0)
        forecasts.append({'date': future_date, 'price': pred})
        price_history.append(pred)

    return forecasts, mae


def main():
    print("=" * 50)
    print("XGBoost 농산물 가격 예측")
    print("=" * 50)

    # 데이터 로드
    print("\n[1/3] 데이터 로드...")
    df = pd.read_csv(DATA_PATH, encoding='utf-8-sig')
    df = df.rename(columns={
        "시점": "period_raw", "시장명": "market_name",
        "품목명": "item_name", "평균가(원/kg)": "price_kg"
    })
    df = df[df['market_name'] == '*전국도매시장']

    # 품목별 학습
    print("\n[2/3] 품목별 학습 및 예측...")
    items = df['item_name'].unique()
    all_results = []

    for item in items:
        item_df = df[df['item_name'] == item].groupby('period_raw')['price_kg'].mean().reset_index()

        if len(item_df) < 30:
            print(f"   {item}: 데이터 부족")
            continue

        forecasts, mae = train_and_forecast(item_df)

        if forecasts is None:
            print(f"   {item}: 학습 실패")
            continue

        last_price = item_df['price_kg'].iloc[-1]
        last_period = item_df['period_raw'].iloc[-1]

        print(f"   {item}: MAE={mae:.0f}원/kg")

        for fc in forecasts:
            all_results.append({
                'item_name': item,
                'last_period': last_period,
                'last_actual_price': round(last_price, 0),
                'forecast_date': fc['date'].strftime('%Y-%m-%d'),
                'predicted_price': round(fc['price'], 0),
                'mae': round(mae, 0)
            })

    # 결과 저장
    print("\n[3/3] 결과 저장 및 S3 업로드...")
    results_df = pd.DataFrame(all_results)
    results_df.to_csv(OUTPUT_PATH, index=False, encoding='utf-8-sig')
    print(f"   로컬: {OUTPUT_PATH}")

    # S3 업로드
    csv_buffer = StringIO()
    results_df.to_csv(csv_buffer, index=False)
    s3.put_object(Bucket=BUCKET_NAME, Key='forecasts/forecast_results.csv', Body=csv_buffer.getvalue())
    print(f"   S3: s3://{BUCKET_NAME}/forecasts/forecast_results.csv")

    # 요약
    print("\n" + "=" * 50)
    print("3개월 후 예측 요약")
    print("=" * 50)

    summary = results_df.groupby('item_name').agg({
        'last_actual_price': 'first',
        'predicted_price': 'last'
    }).reset_index()
    summary['change_pct'] = ((summary['predicted_price'] - summary['last_actual_price']) / summary['last_actual_price'] * 100).round(1)

    for _, row in summary.iterrows():
        arrow = "↑" if row['change_pct'] > 0 else "↓"
        print(f"   {row['item_name']}: {row['last_actual_price']:.0f} -> {row['predicted_price']:.0f} 원/kg ({arrow}{abs(row['change_pct'])}%)")

    print("\n완료!")
    return OUTPUT_PATH


if __name__ == "__main__":
    main()
