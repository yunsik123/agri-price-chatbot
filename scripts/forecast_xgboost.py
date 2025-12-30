"""
농산물 가격 시계열 예측 스크립트 (XGBoost)
- 전체 품목별 3개월 후 가격 예측
- 결과 CSV 저장 → S3 업로드
"""

import pandas as pd
import numpy as np
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
import warnings
import os
from datetime import datetime

warnings.filterwarnings('ignore')

# 경로 설정
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, 'data', 'sample_agri_prices.csv')
OUTPUT_PATH = os.path.join(BASE_DIR, 'data', 'forecast_results.csv')


def parse_period(period_str):
    """'201801상순' -> datetime 변환"""
    year = int(period_str[:4])
    month = int(period_str[4:6])

    if '상순' in period_str:
        day = 5
    elif '중순' in period_str:
        day = 15
    else:  # 하순
        day = 25

    return datetime(year, month, day)


def create_features(df):
    """시계열 특성 생성"""
    df = df.copy()
    df['date'] = df['period_raw'].apply(parse_period)
    df = df.sort_values('date')

    # 기본 시간 특성
    df['year'] = df['date'].dt.year
    df['month'] = df['date'].dt.month
    df['day_of_year'] = df['date'].dt.dayofyear

    # 순환 특성 (계절성 반영)
    df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
    df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)

    # 래그 특성 (과거 가격)
    for lag in [1, 2, 3, 6, 9, 12]:  # 1순~12순 전
        df[f'price_lag_{lag}'] = df['price_kg'].shift(lag)

    # 이동 평균
    df['price_ma_3'] = df['price_kg'].rolling(window=3).mean()
    df['price_ma_6'] = df['price_kg'].rolling(window=6).mean()
    df['price_ma_12'] = df['price_kg'].rolling(window=12).mean()

    # 변동성
    df['price_std_3'] = df['price_kg'].rolling(window=3).std()
    df['price_std_6'] = df['price_kg'].rolling(window=6).std()

    # 추세
    df['price_diff_1'] = df['price_kg'].diff(1)
    df['price_diff_3'] = df['price_kg'].diff(3)

    return df


def train_forecast_model(item_df, forecast_periods=9):
    """
    품목별 XGBoost 모델 학습 및 예측
    forecast_periods=9 (3개월 = 9순)
    """
    df = create_features(item_df)

    # 결측치 제거
    feature_cols = [col for col in df.columns if col.startswith(('price_lag', 'price_ma', 'price_std', 'price_diff', 'month_', 'year', 'month', 'day_of_year'))]
    feature_cols = ['year', 'month', 'day_of_year', 'month_sin', 'month_cos',
                    'price_lag_1', 'price_lag_2', 'price_lag_3', 'price_lag_6', 'price_lag_9', 'price_lag_12',
                    'price_ma_3', 'price_ma_6', 'price_ma_12',
                    'price_std_3', 'price_std_6',
                    'price_diff_1', 'price_diff_3']

    df_clean = df.dropna(subset=feature_cols + ['price_kg'])

    if len(df_clean) < 20:
        return None, None, None

    X = df_clean[feature_cols]
    y = df_clean['price_kg']

    # 학습/테스트 분리 (마지막 20%를 테스트)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    # XGBoost 모델
    model = XGBRegressor(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbosity=0
    )

    model.fit(X_train, y_train)

    # 테스트 성능
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))

    # 미래 예측 (3개월 = 9순)
    last_row = df_clean.iloc[-1:].copy()
    last_date = last_row['date'].values[0]
    last_price = last_row['price_kg'].values[0]

    # 미래 날짜 생성
    future_dates = pd.date_range(start=pd.Timestamp(last_date), periods=forecast_periods+1, freq='10D')[1:]

    forecasts = []
    price_history = df_clean['price_kg'].tolist()

    for i, future_date in enumerate(future_dates):
        # 특성 생성
        future_features = {
            'year': future_date.year,
            'month': future_date.month,
            'day_of_year': future_date.dayofyear,
            'month_sin': np.sin(2 * np.pi * future_date.month / 12),
            'month_cos': np.cos(2 * np.pi * future_date.month / 12),
            'price_lag_1': price_history[-1] if len(price_history) >= 1 else last_price,
            'price_lag_2': price_history[-2] if len(price_history) >= 2 else last_price,
            'price_lag_3': price_history[-3] if len(price_history) >= 3 else last_price,
            'price_lag_6': price_history[-6] if len(price_history) >= 6 else last_price,
            'price_lag_9': price_history[-9] if len(price_history) >= 9 else last_price,
            'price_lag_12': price_history[-12] if len(price_history) >= 12 else last_price,
            'price_ma_3': np.mean(price_history[-3:]) if len(price_history) >= 3 else last_price,
            'price_ma_6': np.mean(price_history[-6:]) if len(price_history) >= 6 else last_price,
            'price_ma_12': np.mean(price_history[-12:]) if len(price_history) >= 12 else last_price,
            'price_std_3': np.std(price_history[-3:]) if len(price_history) >= 3 else 0,
            'price_std_6': np.std(price_history[-6:]) if len(price_history) >= 6 else 0,
            'price_diff_1': price_history[-1] - price_history[-2] if len(price_history) >= 2 else 0,
            'price_diff_3': price_history[-1] - price_history[-4] if len(price_history) >= 4 else 0,
        }

        X_future = pd.DataFrame([future_features])
        pred_price = model.predict(X_future)[0]

        # 음수 방지
        pred_price = max(pred_price, 0)

        forecasts.append({
            'date': future_date,
            'predicted_price': pred_price
        })

        price_history.append(pred_price)

    return forecasts, mae, rmse


def main():
    print("=" * 60)
    print("농산물 가격 예측 (XGBoost)")
    print("=" * 60)

    # 데이터 로드
    print("\n[1/4] 데이터 로드 중...")
    df = pd.read_csv(DATA_PATH, encoding='utf-8-sig')

    # 컬럼 매핑
    column_mapping = {
        "시점": "period_raw",
        "시장코드": "market_code",
        "시장명": "market_name",
        "품목코드": "item_code",
        "품목명": "item_name",
        "품종코드": "variety_code",
        "품종명": "variety_name",
        "총반입량(kg)": "volume_kg",
        "총거래금액(원)": "amount_krw",
        "평균가(원/kg)": "price_kg",
    }
    df = df.rename(columns=column_mapping)

    # 전국도매시장 데이터만 사용 (대표값)
    df = df[df['market_name'] == '*전국도매시장']

    items = df['item_name'].unique()
    print(f"   총 품목 수: {len(items)}")

    # 품목별 예측
    print("\n[2/4] 품목별 모델 학습 및 예측 중...")
    all_results = []

    for item in items:
        item_df = df[df['item_name'] == item].copy()

        # 품종별로 집계 (평균 가격)
        item_agg = item_df.groupby('period_raw').agg({
            'price_kg': 'mean',
            'volume_kg': 'sum'
        }).reset_index()

        if len(item_agg) < 30:
            print(f"   - {item}: 데이터 부족 (건너뜀)")
            continue

        forecasts, mae, rmse = train_forecast_model(item_agg)

        if forecasts is None:
            print(f"   - {item}: 학습 실패")
            continue

        print(f"   - {item}: MAE={mae:.0f}원/kg, RMSE={rmse:.0f}원/kg")

        # 마지막 실제 가격
        last_actual = item_agg['price_kg'].iloc[-1]
        last_period = item_agg['period_raw'].iloc[-1]

        for fc in forecasts:
            all_results.append({
                'item_name': item,
                'last_actual_period': last_period,
                'last_actual_price': last_actual,
                'forecast_date': fc['date'].strftime('%Y-%m-%d'),
                'predicted_price': round(fc['predicted_price'], 0),
                'model_mae': round(mae, 0),
                'model_rmse': round(rmse, 0)
            })

    # 결과 저장
    print("\n[3/4] 예측 결과 저장 중...")
    results_df = pd.DataFrame(all_results)
    results_df.to_csv(OUTPUT_PATH, index=False, encoding='utf-8-sig')
    print(f"   저장 완료: {OUTPUT_PATH}")
    print(f"   총 예측 건수: {len(results_df)}")

    # 요약 출력
    print("\n[4/4] 예측 요약")
    print("-" * 60)

    summary = results_df.groupby('item_name').agg({
        'last_actual_price': 'first',
        'predicted_price': 'last',  # 3개월 후 예측
        'model_mae': 'first'
    }).reset_index()

    summary['change_pct'] = ((summary['predicted_price'] - summary['last_actual_price']) / summary['last_actual_price'] * 100).round(1)

    for _, row in summary.iterrows():
        direction = "상승" if row['change_pct'] > 0 else "하락"
        print(f"   {row['item_name']}: {row['last_actual_price']:.0f} -> {row['predicted_price']:.0f}원/kg ({direction} {abs(row['change_pct']):.1f}%)")

    print("\n" + "=" * 60)
    print("완료!")
    print("=" * 60)

    return OUTPUT_PATH


if __name__ == "__main__":
    main()
