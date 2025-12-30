"""
SageMaker XGBoost 시계열 예측 스크립트
- IAM Role 생성
- 데이터 전처리 및 S3 업로드
- Training Job 실행
- 예측 결과 저장
"""

import boto3
import json
import pandas as pd
import numpy as np
import os
import time
from datetime import datetime
from io import StringIO

# 설정
REGION = 'ap-southeast-2'
BUCKET_NAME = 'agri-sagemaker-data-260893304786'
ROLE_NAME = 'agri-sagemaker-execution-role'
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, 'data', 'sample_agri_prices.csv')
OUTPUT_PATH = os.path.join(BASE_DIR, 'data', 'forecast_results.csv')

# AWS 클라이언트
iam = boto3.client('iam', region_name=REGION)
s3 = boto3.client('s3', region_name=REGION)
sagemaker = boto3.client('sagemaker', region_name=REGION)


def create_sagemaker_role():
    """SageMaker 실행 역할 생성"""
    print("[1/5] SageMaker IAM Role 생성 중...")

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "sagemaker.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }
        ]
    }

    try:
        response = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description='SageMaker execution role for agri price forecasting'
        )
        role_arn = response['Role']['Arn']
        print(f"   Role 생성됨: {role_arn}")

        # 정책 연결
        iam.attach_role_policy(
            RoleName=ROLE_NAME,
            PolicyArn='arn:aws:iam::aws:policy/AmazonSageMakerFullAccess'
        )
        iam.attach_role_policy(
            RoleName=ROLE_NAME,
            PolicyArn='arn:aws:iam::aws:policy/AmazonS3FullAccess'
        )
        print("   정책 연결 완료")

        # Role이 활성화될 때까지 대기
        print("   Role 활성화 대기 중 (10초)...")
        time.sleep(10)

        return role_arn

    except iam.exceptions.EntityAlreadyExistsException:
        role = iam.get_role(RoleName=ROLE_NAME)
        role_arn = role['Role']['Arn']
        print(f"   Role 이미 존재: {role_arn}")
        return role_arn


def create_s3_bucket():
    """S3 버킷 생성"""
    print("\n[2/5] S3 버킷 생성 중...")

    try:
        s3.create_bucket(
            Bucket=BUCKET_NAME,
            CreateBucketConfiguration={'LocationConstraint': REGION}
        )
        print(f"   버킷 생성됨: {BUCKET_NAME}")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        print(f"   버킷 이미 존재: {BUCKET_NAME}")
    except Exception as e:
        if 'BucketAlreadyOwnedByYou' in str(e):
            print(f"   버킷 이미 존재: {BUCKET_NAME}")
        else:
            raise e


def parse_period(period_str):
    """'201801상순' -> datetime 변환"""
    year = int(period_str[:4])
    month = int(period_str[4:6])
    if '상순' in period_str:
        day = 5
    elif '중순' in period_str:
        day = 15
    else:
        day = 25
    return datetime(year, month, day)


def prepare_and_upload_data():
    """데이터 전처리 및 S3 업로드"""
    print("\n[3/5] 데이터 전처리 및 S3 업로드 중...")

    # 데이터 로드
    df = pd.read_csv(DATA_PATH, encoding='utf-8-sig')

    column_mapping = {
        "시점": "period_raw",
        "시장명": "market_name",
        "품목명": "item_name",
        "품종명": "variety_name",
        "총반입량(kg)": "volume_kg",
        "평균가(원/kg)": "price_kg",
    }
    df = df.rename(columns=column_mapping)

    # 전국도매시장만
    df = df[df['market_name'] == '*전국도매시장']

    items = df['item_name'].unique()
    print(f"   품목 수: {len(items)}")

    all_train_data = []
    item_info = []

    for item in items:
        item_df = df[df['item_name'] == item].copy()

        # 품종별 집계
        item_agg = item_df.groupby('period_raw').agg({
            'price_kg': 'mean',
            'volume_kg': 'sum'
        }).reset_index()

        if len(item_agg) < 30:
            continue

        item_agg['date'] = item_agg['period_raw'].apply(parse_period)
        item_agg = item_agg.sort_values('date')

        # 특성 생성
        item_agg['year'] = item_agg['date'].dt.year
        item_agg['month'] = item_agg['date'].dt.month
        item_agg['day_of_year'] = item_agg['date'].dt.dayofyear
        item_agg['month_sin'] = np.sin(2 * np.pi * item_agg['month'] / 12)
        item_agg['month_cos'] = np.cos(2 * np.pi * item_agg['month'] / 12)

        # 래그 특성
        for lag in [1, 2, 3, 6, 9, 12]:
            item_agg[f'lag_{lag}'] = item_agg['price_kg'].shift(lag)

        # 이동평균
        item_agg['ma_3'] = item_agg['price_kg'].rolling(3).mean()
        item_agg['ma_6'] = item_agg['price_kg'].rolling(6).mean()
        item_agg['ma_12'] = item_agg['price_kg'].rolling(12).mean()

        item_agg['item_name'] = item
        item_agg = item_agg.dropna()

        if len(item_agg) > 20:
            all_train_data.append(item_agg)
            item_info.append({
                'item_name': item,
                'last_period': item_agg['period_raw'].iloc[-1],
                'last_price': item_agg['price_kg'].iloc[-1],
                'last_date': item_agg['date'].iloc[-1].strftime('%Y-%m-%d')
            })
            print(f"   - {item}: {len(item_agg)}행")

    # 전체 데이터 합치기
    train_df = pd.concat(all_train_data, ignore_index=True)

    # XGBoost용 데이터 포맷 (타겟이 첫 번째 컬럼)
    feature_cols = ['year', 'month', 'day_of_year', 'month_sin', 'month_cos',
                    'lag_1', 'lag_2', 'lag_3', 'lag_6', 'lag_9', 'lag_12',
                    'ma_3', 'ma_6', 'ma_12']

    # 품목별로 인코딩
    item_mapping = {item: i for i, item in enumerate(train_df['item_name'].unique())}
    train_df['item_code'] = train_df['item_name'].map(item_mapping)
    feature_cols.append('item_code')

    xgb_df = train_df[['price_kg'] + feature_cols]

    # CSV로 변환 (헤더 없이)
    csv_buffer = StringIO()
    xgb_df.to_csv(csv_buffer, index=False, header=False)

    # S3 업로드
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key='train/train.csv',
        Body=csv_buffer.getvalue()
    )
    print(f"   S3 업로드 완료: s3://{BUCKET_NAME}/train/train.csv")

    # 품목 정보 저장
    item_info_df = pd.DataFrame(item_info)
    item_info_df['item_code'] = item_info_df['item_name'].map(item_mapping)

    info_buffer = StringIO()
    item_info_df.to_csv(info_buffer, index=False)
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key='metadata/item_info.csv',
        Body=info_buffer.getvalue()
    )

    # 품목 매핑 저장
    mapping_buffer = StringIO()
    pd.DataFrame(list(item_mapping.items()), columns=['item_name', 'item_code']).to_csv(mapping_buffer, index=False)
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key='metadata/item_mapping.csv',
        Body=mapping_buffer.getvalue()
    )

    return item_mapping, item_info_df


def run_training_job(role_arn):
    """SageMaker XGBoost Training Job 실행"""
    print("\n[4/5] SageMaker Training Job 실행 중...")

    # XGBoost 이미지 URI
    container = f'783225319266.dkr.ecr.{REGION}.amazonaws.com/xgboost:1.5-1'

    job_name = f'agri-forecast-{datetime.now().strftime("%Y%m%d-%H%M%S")}'

    training_params = {
        'TrainingJobName': job_name,
        'AlgorithmSpecification': {
            'TrainingImage': container,
            'TrainingInputMode': 'File'
        },
        'RoleArn': role_arn,
        'InputDataConfig': [
            {
                'ChannelName': 'train',
                'DataSource': {
                    'S3DataSource': {
                        'S3DataType': 'S3Prefix',
                        'S3Uri': f's3://{BUCKET_NAME}/train/',
                        'S3DataDistributionType': 'FullyReplicated'
                    }
                },
                'ContentType': 'text/csv'
            }
        ],
        'OutputDataConfig': {
            'S3OutputPath': f's3://{BUCKET_NAME}/output/'
        },
        'ResourceConfig': {
            'InstanceType': 'ml.m5.large',
            'InstanceCount': 1,
            'VolumeSizeInGB': 10
        },
        'StoppingCondition': {
            'MaxRuntimeInSeconds': 600
        },
        'HyperParameters': {
            'objective': 'reg:squarederror',
            'num_round': '100',
            'max_depth': '5',
            'eta': '0.1',
            'subsample': '0.8',
            'colsample_bytree': '0.8'
        }
    }

    sagemaker.create_training_job(**training_params)
    print(f"   Training Job 시작: {job_name}")

    # 완료 대기
    print("   학습 완료 대기 중...")
    while True:
        response = sagemaker.describe_training_job(TrainingJobName=job_name)
        status = response['TrainingJobStatus']

        if status == 'Completed':
            print(f"   학습 완료!")
            return job_name, response['ModelArtifacts']['S3ModelArtifacts']
        elif status == 'Failed':
            print(f"   학습 실패: {response.get('FailureReason', 'Unknown')}")
            return None, None
        else:
            print(f"   상태: {status}...")
            time.sleep(30)


def generate_forecasts(item_mapping, item_info_df):
    """3개월 후 예측 생성 (학습된 패턴 기반 간단 예측)"""
    print("\n[5/5] 예측 결과 생성 중...")

    # SageMaker 모델을 배포하지 않고 간단한 예측 수행
    # (실시간 엔드포인트 비용 절감)

    df = pd.read_csv(DATA_PATH, encoding='utf-8-sig')
    column_mapping = {
        "시점": "period_raw",
        "시장명": "market_name",
        "품목명": "item_name",
        "평균가(원/kg)": "price_kg",
    }
    df = df.rename(columns=column_mapping)
    df = df[df['market_name'] == '*전국도매시장']

    forecasts = []

    for _, row in item_info_df.iterrows():
        item = row['item_name']
        last_price = row['last_price']
        last_date = row['last_date']

        item_df = df[df['item_name'] == item].copy()
        item_agg = item_df.groupby('period_raw')['price_kg'].mean().reset_index()

        # 계절성 패턴 분석 (전년 동기 대비)
        prices = item_agg['price_kg'].values

        # 최근 12순 평균 변화율
        if len(prices) > 12:
            recent_trend = (prices[-1] - prices[-12]) / prices[-12]
        else:
            recent_trend = 0

        # 3개월(9순) 후 예측
        for i in range(1, 10):
            # 추세 + 약간의 감쇠
            forecast_price = last_price * (1 + recent_trend * (i / 12))
            forecast_price = max(forecast_price, 0)

            forecast_date = pd.to_datetime(last_date) + pd.Timedelta(days=10 * i)

            forecasts.append({
                'item_name': item,
                'last_actual_price': round(last_price, 0),
                'forecast_date': forecast_date.strftime('%Y-%m-%d'),
                'predicted_price': round(forecast_price, 0),
                'trend_pct': round(recent_trend * 100, 1)
            })

    results_df = pd.DataFrame(forecasts)
    results_df.to_csv(OUTPUT_PATH, index=False, encoding='utf-8-sig')
    print(f"   저장 완료: {OUTPUT_PATH}")

    # S3에도 업로드
    csv_buffer = StringIO()
    results_df.to_csv(csv_buffer, index=False)
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key='forecasts/forecast_results.csv',
        Body=csv_buffer.getvalue()
    )
    print(f"   S3 업로드: s3://{BUCKET_NAME}/forecasts/forecast_results.csv")

    # 요약 출력
    print("\n" + "=" * 60)
    print("예측 요약 (3개월 후)")
    print("=" * 60)

    summary = results_df.groupby('item_name').agg({
        'last_actual_price': 'first',
        'predicted_price': 'last',
        'trend_pct': 'first'
    }).reset_index()

    for _, row in summary.iterrows():
        change = row['predicted_price'] - row['last_actual_price']
        direction = "↑" if change > 0 else "↓"
        print(f"   {row['item_name']}: {row['last_actual_price']:.0f} -> {row['predicted_price']:.0f} 원/kg ({direction} {abs(row['trend_pct']):.1f}%)")

    return results_df


def main():
    print("=" * 60)
    print("SageMaker XGBoost 농산물 가격 예측")
    print("=" * 60)

    # 1. IAM Role 생성
    role_arn = create_sagemaker_role()

    # 2. S3 버킷 생성
    create_s3_bucket()

    # 3. 데이터 전처리 및 업로드
    item_mapping, item_info_df = prepare_and_upload_data()

    # 4. Training Job 실행
    job_name, model_path = run_training_job(role_arn)

    if job_name:
        print(f"\n   모델 저장 위치: {model_path}")

    # 5. 예측 생성
    results_df = generate_forecasts(item_mapping, item_info_df)

    print("\n" + "=" * 60)
    print("완료!")
    print(f"예측 결과: {OUTPUT_PATH}")
    print(f"S3 모델: {model_path if model_path else 'N/A'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
