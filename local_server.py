"""
Local Development Server
- FastAPI 기반 로컬 테스트 서버
- Lambda 함수와 동일한 로직 사용
- 프론트엔드 정적 파일 서빙
"""
import os
import sys
import json
import uuid
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any

# 환경변수 설정
os.environ.setdefault("DATA_PATH", str(Path(__file__).parent / "data" / "sample_agri_prices.csv"))
os.environ.setdefault("USE_LOCAL", "true")

# 모듈 임포트
from src.nlu import parse as nlu_parse
from src.query import execute_query
from src.features import calculate_summary, enrich_summary_with_context
from src.narrative import generate_narrative
from src.schema import FilterRequest
from src.data_loader import load_data, get_dim_dict

# FastAPI 앱
app = FastAPI(
    title="Agricultural Price Chatbot API",
    description="농산물 가격 분석 챗봇 로컬 서버",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Request/Response 모델
# ============================================================

class QueryRequest(BaseModel):
    question: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    clarify_answers: Optional[Dict[str, str]] = None


# ============================================================
# API 엔드포인트
# ============================================================

@app.post("/api/query")
async def query(request: QueryRequest):
    """
    메인 쿼리 엔드포인트
    - 자연어 질문 또는 필터로 데이터 분석
    """
    request_id = str(uuid.uuid4())
    warnings = []

    try:
        # 필터 직접 지정
        if request.filters:
            try:
                filter_obj = FilterRequest(**request.filters)
                filters = filter_obj.model_dump()
            except Exception as e:
                return JSONResponse(
                    status_code=400,
                    content={"error": {"code": "INVALID_FILTERS", "message": str(e)}}
                )

        # 자연어 질문
        elif request.question:
            nlu_result, nlu_warnings = nlu_parse(request.question, request.clarify_answers)
            warnings.extend(nlu_warnings)

            if nlu_result.get("type") == "clarify":
                return {
                    "type": "clarify",
                    "filters": None,
                    "series": [],
                    "summary": None,
                    "narrative": "",
                    "warnings": warnings,
                    "clarification": {
                        "draft_filters": nlu_result.get("draft_filters", {}),
                        "questions": nlu_result.get("questions", [])
                    },
                    "request_id": request_id
                }

            filters = nlu_result.get("filters", {})

        else:
            return JSONResponse(
                status_code=400,
                content={"error": {"code": "MISSING_INPUT", "message": "question 또는 filters가 필요합니다."}}
            )

        # 데이터 조회
        series, query_warnings = execute_query(filters)
        warnings.extend(query_warnings)

        if not series:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "NO_DATA", "message": "조건에 맞는 데이터가 없습니다."}}
            )

        # 요약 계산
        summary = calculate_summary(series, filters)
        summary = enrich_summary_with_context(summary, filters, series)

        # 내러티브 생성
        narrative = ""
        if filters.get("explain", True):
            try:
                narrative = generate_narrative(filters, series, summary)
            except Exception as e:
                warnings.append(f"내러티브 생성 실패: {str(e)}")
                narrative = f"{filters.get('item_name', '품목')} 분석이 완료되었습니다."

        return {
            "type": "result",
            "filters": filters,
            "series": series,
            "summary": summary,
            "narrative": narrative,
            "warnings": warnings,
            "clarification": None,
            "request_id": request_id
        }

    except Exception as e:
        import traceback
        print(f"Error: {traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": str(e)}}
        )


@app.get("/api/health")
async def health():
    """헬스 체크"""
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/api/dimensions")
async def dimensions():
    """품목/품종/시장 목록"""
    try:
        dim_dict = get_dim_dict()
        return dim_dict
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": str(e)}}
        )


# ============================================================
# 정적 파일 서빙
# ============================================================

# 프론트엔드 정적 파일
frontend_path = Path(__file__).parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")


@app.get("/")
async def root():
    """메인 페이지"""
    index_file = frontend_path / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "Frontend not found. API is running at /api/query"}


# ============================================================
# 데이터 미리 로딩
# ============================================================

@app.on_event("startup")
async def startup_event():
    """서버 시작 시 데이터 로딩"""
    try:
        load_data()
        get_dim_dict()
        print("Data preloaded successfully!")
    except Exception as e:
        print(f"Data preload failed: {e}")


# ============================================================
# 메인 실행
# ============================================================

if __name__ == "__main__":
    import uvicorn

    print("=" * 50)
    print("  Agricultural Price Chatbot - Local Server")
    print("=" * 50)
    print()
    print("Starting server...")
    print()
    print("Access the chatbot at:")
    print("  http://localhost:8000")
    print()
    print("API endpoint:")
    print("  http://localhost:8000/api/query")
    print()

    uvicorn.run(
        "local_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
