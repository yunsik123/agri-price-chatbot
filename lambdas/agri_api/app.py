"""
Lambda 핸들러: 농산물 가격 분석 API
- 자연어 질문 → 필터 추출 → 데이터 조회 → 요약/설명 생성
- 가격 예측 API
"""
import json
import uuid
import sys
import os
import boto3
from io import StringIO

# Lambda 환경에서 src 모듈 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.schema import (
    FilterRequest, APIResponse, SummaryStats, SeriesPoint,
    create_error_response, create_clarify_response
)
from src.nlu import parse as nlu_parse
from src.query import execute_query
from src.features import calculate_summary, enrich_summary_with_context
from src.narrative import generate_narrative
from src.data_loader import load_data, get_dim_dict


# CORS 헤더
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "content-type",
    "Access-Control-Allow-Methods": "OPTIONS,POST,GET",
    "Content-Type": "application/json"
}

# S3 설정 (예측 데이터)
FORECAST_BUCKET = 'agri-sagemaker-data-260893304786'
FORECAST_KEY = 'forecasts/forecast_results.csv'
REGION = 'ap-southeast-2'

# 예측 데이터 캐시
_forecast_cache = None


def load_forecast_data():
    """S3에서 예측 데이터 로드"""
    global _forecast_cache

    if _forecast_cache is not None:
        return _forecast_cache

    try:
        s3 = boto3.client('s3', region_name=REGION)
        response = s3.get_object(Bucket=FORECAST_BUCKET, Key=FORECAST_KEY)
        csv_content = response['Body'].read().decode('utf-8-sig')

        # CSV 파싱
        import csv
        reader = csv.DictReader(StringIO(csv_content))
        _forecast_cache = list(reader)
        return _forecast_cache
    except Exception as e:
        print(f"Forecast data load error: {e}")
        return []


def get_forecast_summary():
    """품목별 예측 요약"""
    data = load_forecast_data()
    if not data:
        return []

    # 품목별 그룹화
    items = {}
    for row in data:
        item_name = row['item_name']
        if item_name not in items:
            items[item_name] = {
                'item_name': item_name,
                'last_actual_price': float(row['last_actual_price']),
                'forecasts': []
            }
        items[item_name]['forecasts'].append({
            'date': row['forecast_date'],
            'price': float(row['predicted_price'])
        })

    # 요약 생성
    result = []
    for item_name, item_data in items.items():
        forecasts = item_data['forecasts']
        last_price = item_data['last_actual_price']
        final_price = forecasts[-1]['price'] if forecasts else last_price

        change_pct = ((final_price - last_price) / last_price * 100) if last_price > 0 else 0

        result.append({
            'item_name': item_name,
            'last_actual_price': last_price,
            'predicted_price_3m': final_price,
            'change_pct': round(change_pct, 1),
            'forecasts': forecasts
        })

    return result


def create_response(status_code: int, body: dict) -> dict:
    """API Gateway 응답 형식 생성"""
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, ensure_ascii=False, default=str)
    }


def handler(event, context):
    """
    Lambda 메인 핸들러

    엔드포인트:
    - POST /api/query: 자연어 질문 처리
    - GET /api/forecast: 가격 예측 데이터

    입력 형태:
    A) {"question": "..."} - 자연어
    B) {"filters": {...}} - 필터 직접 지정
    C) {"question": "...", "clarify_answers": {...}} - Clarification 답변
    """
    request_id = str(uuid.uuid4())

    try:
        # HTTP 메서드 및 경로 확인
        http_method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method", "")
        path = event.get("path") or event.get("rawPath") or ""

        # OPTIONS 요청 처리 (CORS preflight)
        if http_method == "OPTIONS":
            return create_response(200, {"message": "OK"})

        # 예측 API 처리
        if "/forecast" in path and http_method == "GET":
            forecasts = get_forecast_summary()
            return create_response(200, {
                "type": "forecast",
                "data": forecasts,
                "request_id": request_id
            })

        # 요청 본문 파싱
        body = event.get("body", "{}")
        if isinstance(body, str):
            body = json.loads(body)

        question = body.get("question")
        filters_input = body.get("filters")
        clarify_answers = body.get("clarify_answers")

        warnings = []

        # ============================================================
        # 1. 필터 추출/검증
        # ============================================================

        if filters_input:
            # B) 필터 직접 지정
            try:
                filter_obj = FilterRequest(**filters_input)
                filters = filter_obj.model_dump()
            except Exception as e:
                return create_response(400, create_error_response(
                    "INVALID_FILTERS",
                    f"필터 스키마 오류: {str(e)}",
                    request_id
                ))

        elif question:
            # A) 또는 C) 자연어 질문
            nlu_result, nlu_warnings = nlu_parse(question, clarify_answers)
            warnings.extend(nlu_warnings)

            if nlu_result.get("type") == "clarify":
                # Clarification 필요
                return create_response(200, {
                    "type": "clarify",
                    "filters": None,
                    "series": [],
                    "summary": None,
                    "narrative": "",
                    "warnings": ["질문이 애매하여 확인이 필요합니다."] + warnings,
                    "clarification": {
                        "draft_filters": nlu_result.get("draft_filters", {}),
                        "questions": nlu_result.get("questions", [])
                    },
                    "request_id": request_id
                })

            filters = nlu_result.get("filters", {})

        else:
            return create_response(400, create_error_response(
                "MISSING_INPUT",
                "question 또는 filters가 필요합니다.",
                request_id
            ))

        # ============================================================
        # 2. 데이터 조회/집계
        # ============================================================

        series, query_warnings = execute_query(filters)
        warnings.extend(query_warnings)

        if not series:
            return create_response(404, create_error_response(
                "NO_DATA",
                "조건에 맞는 데이터가 없습니다.",
                request_id
            ))

        # ============================================================
        # 3. 요약 통계 계산
        # ============================================================

        summary = calculate_summary(series, filters)
        summary = enrich_summary_with_context(summary, filters, series)

        # ============================================================
        # 4. 내러티브 생성 (옵션)
        # ============================================================

        narrative = ""
        if filters.get("explain", True):
            narrative = generate_narrative(filters, series, summary)

        # ============================================================
        # 5. 최종 응답 구성
        # ============================================================

        response_body = {
            "type": "result",
            "filters": filters,
            "series": series,
            "summary": summary,
            "narrative": narrative,
            "warnings": warnings,
            "clarification": None,
            "request_id": request_id
        }

        return create_response(200, response_body)

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Error: {error_detail}")

        return create_response(500, create_error_response(
            "INTERNAL_ERROR",
            f"내부 오류가 발생했습니다: {str(e)}",
            request_id
        ))


# 콜드 스타트 최적화: 데이터 미리 로딩
try:
    load_data()
    get_dim_dict()
    print("Data preloaded successfully")
except Exception as e:
    print(f"Data preload failed: {e}")
