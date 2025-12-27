"""
Streamlit 대시보드: 농산물 가격 분석 챗봇 UI
"""
import os
import sys
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 로컬 실행 시 직접 모듈 사용 가능
USE_LOCAL = os.environ.get("USE_LOCAL", "true").lower() == "true"
API_ENDPOINT = os.environ.get("API_ENDPOINT", "http://localhost:8000/query")

# 페이지 설정
st.set_page_config(
    page_title="농산물 가격 분석 챗봇",
    page_icon="🌾",
    layout="wide"
)

# 스타일
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
    }
    .metric-value {
        font-size: 24px;
        font-weight: bold;
        color: #1f77b4;
    }
    .metric-label {
        font-size: 14px;
        color: #666;
    }
    .positive { color: #28a745; }
    .negative { color: #dc3545; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# API 호출 함수
# ============================================================

def call_api(payload: dict) -> dict:
    """API 호출 (로컬 또는 원격)"""
    if USE_LOCAL:
        return call_local(payload)
    else:
        return call_remote(payload)


def call_local(payload: dict) -> dict:
    """로컬 모듈 직접 호출"""
    try:
        from src.nlu import parse as nlu_parse
        from src.query import execute_query
        from src.features import calculate_summary, enrich_summary_with_context
        from src.narrative import generate_narrative
        from src.schema import FilterRequest
        import uuid

        request_id = str(uuid.uuid4())
        warnings = []

        question = payload.get("question")
        filters_input = payload.get("filters")
        clarify_answers = payload.get("clarify_answers")

        # 필터 추출
        if filters_input:
            filter_obj = FilterRequest(**filters_input)
            filters = filter_obj.model_dump()
        elif question:
            nlu_result, nlu_warnings = nlu_parse(question, clarify_answers)
            warnings.extend(nlu_warnings)

            if nlu_result.get("type") == "clarify":
                return {
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
                }

            filters = nlu_result.get("filters", {})
        else:
            return {"error": {"code": "MISSING_INPUT", "message": "question 또는 filters가 필요합니다."}}

        # 데이터 조회
        series, query_warnings = execute_query(filters)
        warnings.extend(query_warnings)

        if not series:
            return {"error": {"code": "NO_DATA", "message": "조건에 맞는 데이터가 없습니다."}}

        # 요약 계산
        summary = calculate_summary(series, filters)
        summary = enrich_summary_with_context(summary, filters, series)

        # 내러티브 생성
        narrative = ""
        if filters.get("explain", True):
            narrative = generate_narrative(filters, series, summary)

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
        return {"error": {"code": "LOCAL_ERROR", "message": str(e), "detail": traceback.format_exc()}}


def call_remote(payload: dict) -> dict:
    """원격 API 호출"""
    try:
        response = requests.post(API_ENDPOINT, json=payload, timeout=30)
        return response.json()
    except Exception as e:
        return {"error": {"code": "API_ERROR", "message": str(e)}}


# ============================================================
# 차트 생성 함수
# ============================================================

def create_price_chart(series: list, filters: dict) -> go.Figure:
    """가격 추세 차트"""
    df = pd.DataFrame(series)
    df["date"] = pd.to_datetime(df["date"])

    chart_type = filters.get("chart_type", "trend")

    if chart_type == "compare_markets" and "market_name" in df.columns:
        # 시장별 비교 차트
        fig = px.line(
            df, x="date", y="price", color="market_name",
            title="시장별 가격 비교",
            labels={"date": "날짜", "price": "가격(원/kg)", "market_name": "시장"}
        )
    else:
        # 단일 추세 차트
        fig = px.line(
            df, x="date", y="price",
            title=f"{filters.get('item_name', '')} 가격 추세",
            labels={"date": "날짜", "price": "가격(원/kg)"}
        )
        fig.update_traces(line_color="#1f77b4")

    fig.update_layout(
        xaxis_title="날짜",
        yaxis_title="가격 (원/kg)",
        hovermode="x unified"
    )

    return fig


def create_volume_chart(series: list, filters: dict) -> go.Figure:
    """반입량 차트"""
    df = pd.DataFrame(series)
    df["date"] = pd.to_datetime(df["date"])

    chart_type = filters.get("chart_type", "trend")

    if chart_type == "compare_markets" and "market_name" in df.columns:
        fig = px.bar(
            df, x="date", y="volume", color="market_name",
            title="시장별 반입량 비교",
            labels={"date": "날짜", "volume": "반입량(kg)", "market_name": "시장"}
        )
    else:
        fig = px.bar(
            df, x="date", y="volume",
            title=f"{filters.get('item_name', '')} 반입량",
            labels={"date": "날짜", "volume": "반입량(kg)"}
        )
        fig.update_traces(marker_color="#2ca02c")

    fig.update_layout(
        xaxis_title="날짜",
        yaxis_title="반입량 (kg)",
        hovermode="x unified"
    )

    return fig


def create_volatility_chart(series: list, filters: dict) -> go.Figure:
    """변동성 차트"""
    df = pd.DataFrame(series)
    df["date"] = pd.to_datetime(df["date"])

    if "volatility" in df.columns:
        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=df["date"], y=df["price"],
            name="가격",
            line=dict(color="#1f77b4")
        ))

        fig.add_trace(go.Scatter(
            x=df["date"], y=df["volatility"],
            name="변동성",
            yaxis="y2",
            line=dict(color="#ff7f0e", dash="dot")
        ))

        fig.update_layout(
            title=f"{filters.get('item_name', '')} 가격 및 변동성",
            xaxis_title="날짜",
            yaxis=dict(title="가격 (원/kg)", side="left"),
            yaxis2=dict(title="변동성", side="right", overlaying="y"),
            hovermode="x unified"
        )
    else:
        fig = create_price_chart(series, filters)

    return fig


# ============================================================
# 메트릭 카드 표시
# ============================================================

def display_metrics(summary: dict):
    """요약 메트릭 카드 표시"""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        value = summary.get("latest_price")
        if value:
            st.metric("최근 가격", f"{value:,.0f}원/kg")
        else:
            st.metric("최근 가격", "N/A")

    with col2:
        value = summary.get("latest_volume")
        if value:
            st.metric("최근 반입량", f"{value:,.0f}kg")
        else:
            st.metric("최근 반입량", "N/A")

    with col3:
        value = summary.get("wow_price_pct")
        if value is not None:
            delta_color = "normal" if value >= 0 else "inverse"
            st.metric("전주 대비", f"{value:+.1f}%", delta=f"{value:+.1f}%", delta_color=delta_color)
        else:
            st.metric("전주 대비", "N/A")

    with col4:
        value = summary.get("volatility_14d")
        if value:
            st.metric("변동성(14일)", f"{value:,.0f}")
        else:
            st.metric("변동성(14일)", "N/A")


# ============================================================
# Clarification UI
# ============================================================

def display_clarification(clarification: dict, original_question: str):
    """Clarification 질문 표시"""
    st.warning("질문이 애매합니다. 아래 항목을 선택해주세요.")

    questions = clarification.get("questions", [])
    answers = {}

    for q in questions:
        q_id = q.get("id", "unknown")
        question_text = q.get("question", "")
        options = q.get("options", [])
        default = q.get("default")

        default_idx = options.index(default) if default in options else 0
        selected = st.radio(question_text, options, index=default_idx, key=f"clarify_{q_id}")
        answers[q_id] = selected

    if st.button("적용하기"):
        st.session_state["clarify_answers"] = answers
        st.session_state["original_question"] = original_question
        st.rerun()


# ============================================================
# 메인 앱
# ============================================================

def main():
    st.title("🌾 농산물 가격 분석 챗봇")
    st.markdown("자연어로 질문하면 도매시장 가격 데이터를 분석해드립니다.")

    # 세션 상태 초기화
    if "clarify_answers" not in st.session_state:
        st.session_state["clarify_answers"] = None
    if "original_question" not in st.session_state:
        st.session_state["original_question"] = None

    # 사이드바: 필터 UI (수동 입력)
    with st.sidebar:
        st.header("수동 필터 설정")
        st.markdown("자연어 대신 직접 필터를 지정할 수 있습니다.")

        use_manual = st.checkbox("수동 필터 사용")

        if use_manual:
            item_name = st.text_input("품목명", value="감자")
            variety_name = st.text_input("품종명 (선택)", value="")
            market_name = st.text_input("시장명", value="전국도매시장")
            date_from = st.date_input("시작일", value=datetime.now() - timedelta(days=90))
            date_to = st.date_input("종료일", value=datetime.now())
            chart_type = st.selectbox("차트 유형", ["trend", "compare_markets", "volume_price", "volatility"])

            if st.button("분석하기", key="manual_analyze"):
                manual_filters = {
                    "item_name": item_name,
                    "variety_name": variety_name if variety_name else None,
                    "market_name": market_name,
                    "date_from": date_from.strftime("%Y-%m-%d"),
                    "date_to": date_to.strftime("%Y-%m-%d"),
                    "chart_type": chart_type,
                    "explain": True
                }
                st.session_state["manual_filters"] = manual_filters

    # 메인 영역: 질문 입력
    st.markdown("---")

    # 예시 질문
    st.markdown("**예시 질문:**")
    example_questions = [
        "감자 수미, 최근 6개월 가격 추세 보여줘",
        "양파, 전국도매시장, 2019년 가격과 반입량 같이 보여줘",
        "배추, 최근 3개월 변동성(급등락) 큰 구간 알려줘",
        "마늘, 시장별 비교해줘(상위 5개 시장)",
        "대파, 최근 한달 가격이 전월 대비 얼마나 올랐어?"
    ]

    col1, col2 = st.columns(2)
    with col1:
        for i, q in enumerate(example_questions[:3]):
            if st.button(q, key=f"example_{i}"):
                st.session_state["question"] = q
    with col2:
        for i, q in enumerate(example_questions[3:]):
            if st.button(q, key=f"example_{i+3}"):
                st.session_state["question"] = q

    # 질문 입력창
    question = st.text_input(
        "질문을 입력하세요:",
        value=st.session_state.get("question", ""),
        placeholder="예: 감자 수미, 최근 6개월 가격 추세 보여줘"
    )

    # 분석 실행
    if st.button("🔍 분석하기", type="primary") or st.session_state.get("clarify_answers"):
        with st.spinner("분석 중..."):
            # Clarification 답변이 있으면 사용
            if st.session_state.get("clarify_answers"):
                payload = {
                    "question": st.session_state.get("original_question", question),
                    "clarify_answers": st.session_state["clarify_answers"]
                }
                st.session_state["clarify_answers"] = None
            # 수동 필터 사용
            elif st.session_state.get("manual_filters"):
                payload = {"filters": st.session_state["manual_filters"]}
                st.session_state["manual_filters"] = None
            # 자연어 질문
            else:
                payload = {"question": question}

            # API 호출
            result = call_api(payload)

            # 에러 처리
            if "error" in result:
                st.error(f"오류: {result['error'].get('message', '알 수 없는 오류')}")
                return

            # Clarification 필요
            if result.get("type") == "clarify":
                display_clarification(result.get("clarification", {}), question)
                return

            # 경고 표시
            warnings = result.get("warnings", [])
            if warnings:
                for w in warnings:
                    st.warning(w)

            # 결과 표시
            filters = result.get("filters", {})
            series = result.get("series", [])
            summary = result.get("summary", {})
            narrative = result.get("narrative", "")

            # 메트릭 카드
            st.subheader("📊 요약 지표")
            display_metrics(summary)

            # 차트
            st.markdown("---")

            chart_type = filters.get("chart_type", "trend")

            if chart_type == "volatility":
                st.plotly_chart(create_volatility_chart(series, filters), use_container_width=True)
            else:
                col1, col2 = st.columns(2)
                with col1:
                    st.plotly_chart(create_price_chart(series, filters), use_container_width=True)
                with col2:
                    st.plotly_chart(create_volume_chart(series, filters), use_container_width=True)

            # 내러티브
            if narrative:
                st.markdown("---")
                st.subheader("📝 분석 설명")
                st.markdown(narrative)

            # 디버그 정보 (접기)
            with st.expander("상세 정보"):
                st.json({
                    "filters": filters,
                    "summary": summary,
                    "data_points": len(series),
                    "request_id": result.get("request_id")
                })


if __name__ == "__main__":
    main()
