# AWS AI Service 기반 농산물(도매시장) 가격 분석·시각화 챗봇

## 프로젝트 개요
- **리전**: ap-southeast-2
- **Bedrock 모델**: amazon.titan-text-express-v1 (Claude 계열 사용 안함)
- **Lambda**: agri-bedrock-chat-prod (Python 3.10, Timeout 30초, 512MB)
- **아키텍처**: Serverless (S3 + API Gateway + Lambda + Bedrock)

## 배포된 리소스

| 서비스 | 리소스명/ID | 설명 |
|--------|-------------|------|
| **S3** | agri-chatbot-frontend-260893304786-prod | 정적 웹 호스팅 |
| **Lambda** | agri-bedrock-chat-prod | 백엔드 API 핸들러 |
| **API Gateway** | xqrsjykrnb | HTTP API |
| **Lambda Layer** | AWSSDKPandas-Python310 | pandas/numpy 라이브러리 |
| **IAM Role** | agri-chatbot-lambda-role-prod | Lambda 실행 역할 |

### 접속 URL
- **웹사이트**: http://agri-chatbot-frontend-260893304786-prod.s3-website-ap-southeast-2.amazonaws.com
- **API Endpoint**: https://xqrsjykrnb.execute-api.ap-southeast-2.amazonaws.com/prod/api/query

## 핵심 원칙
- **LLM은 SQL을 직접 생성/실행하지 않음**
- LLM은 "필터 JSON만" 출력
- 실제 데이터 조회는 서버 코드(쿼리빌더/집계 코드)가 수행

---

## A. 아키텍처/모듈 구조

### 시스템 아키텍처
```
┌─────────────────────────────────────────────────────────────────┐
│                        사용자 브라우저                            │
│  ┌─────────────────────┐    ┌─────────────────────────────────┐ │
│  │   대시보드 (좌측)     │    │     AI 채팅 (우측)              │ │
│  │  - 메트릭 카드       │    │  - 자연어 질문                  │ │
│  │  - 가격 차트         │    │  - 응답 표시                    │ │
│  │  - 반입량 차트       │    │  - Clarification UI            │ │
│  └─────────────────────┘    └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    S3 Static Website Hosting                     │
│                 (frontend/index.html + Plotly.js)                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    API Gateway (HTTP API)                        │
│                POST /api/query, GET /api/health                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Lambda Function                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │   NLU    │→ │  Query   │→ │ Features │→ │    Narrative     │ │
│  │(Bedrock) │  │(pandas)  │  │(summary) │  │   (Bedrock)      │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘ │
│                      │                                           │
│              ┌───────▼───────┐                                   │
│              │  CSV 데이터    │                                   │
│              │ (Lambda 내장)  │                                   │
│              └───────────────┘                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Amazon Bedrock                                │
│                 (Titan Text Express v1)                          │
└─────────────────────────────────────────────────────────────────┘
```

### 프로젝트 폴더 구조
```
aws_agri/
├── frontend/
│   └── index.html          # 웹 UI (대시보드 + 채팅)
├── lambdas/agri_api/
│   ├── app.py              # Lambda 핸들러(메인)
│   └── requirements.txt
├── src/
│   ├── schema.py           # Filter 스키마(Pydantic) + 응답 스키마
│   ├── nlu.py              # Bedrock Titan 기반 필터 추출(JSON only)
│   ├── data_loader.py      # CSV 로딩/컬럼 매핑/캐싱
│   ├── query.py            # 필터→데이터프레임 필터링/집계
│   ├── features.py         # WoW/MoM/변동성/급등락 등 요약지표 생성
│   └── narrative.py        # series/summary 기반 설명 프롬프트 + Titan 호출
├── streamlit_app/
│   └── app.py              # Streamlit 대시보드 (레거시)
├── tests/                  # pytest 테스트
├── data/                   # CSV 데이터
├── local_server.py         # 로컬 개발 서버 (FastAPI)
├── deploy_aws.ps1          # AWS 배포 스크립트
├── template.yaml           # SAM 템플릿
└── README.md
```

---

## B. 스키마

### FilterRequest (LLM 출력 목표)
```python
item_name: str                    # 필수; 품목명
variety_name: Optional[str]       # 선택; 품종명
market_name: Optional[str]        # 선택; 없으면 "전국도매시장"
date_from: Optional[str]          # YYYY-MM-DD
date_to: Optional[str]            # YYYY-MM-DD
chart_type: Literal["trend","compare_markets","volume_price","volatility"]  # 기본 "trend"
metrics: List[Literal["price","volume"]]  # 기본 ["price","volume"]
granularity: Literal["daily","weekly"]    # 기본 "weekly"
top_n_markets: Optional[int]      # compare_markets용; 기본 5
explain: bool                     # 기본 True
intent: Optional[Literal["normal","high_avg_price","high_price_change","high_volatility"]]  # 기본 "normal"
window_days: Optional[int]        # 기본 30
```

### Response 스키마
```python
type: Literal["result","clarify"]
filters: FilterRequest            # 정규화된 최종 필터
series: List[SeriesPoint]
summary: SummaryStats
narrative: str
warnings: List[str]
clarification: Optional[Clarification]
request_id: str
```

---

## C. 자연어→필터 변환 (NLU)

### LLM 출력 타입 (2가지만 허용)

**(A) 확정 필터:**
```json
{
  "type": "filters",
  "filters": { ...FilterRequest... },
  "warnings": ["...optional..."]
}
```

**(B) 확인 질문:**
```json
{
  "type": "clarify",
  "draft_filters": { ...Partial<FilterRequest>... },
  "questions": [
    {
      "id": "expensive_meaning",
      "question": "...",
      "options": ["..."],
      "default": "..."
    }
  ],
  "warnings": ["...optional..."]
}
```

### 날짜 표현 변환 규칙
- 상순: 1~10일 (대표일: 05일)
- 중순: 11~20일 (대표일: 15일)
- 하순: 21~말일 (대표일: 25일)

### Clarification 트리거
- "요즘/최근/요새" - 기간 불명확
- "비싼/싼" - 기준 불명확
- 품목/품종/시장 후보 다수 매칭

### expensive_meaning 옵션
- `high_avg_price`: 평균가격이 높은 시장 Top-N
- `high_price_change`: 가격 상승률이 큰 시장/구간
- `high_volatility`: 변동성이 큰 구간/시장

---

## D. 데이터 컬럼 매핑

### 원본 → 표준 컬럼
```python
COLUMN_MAPPING = {
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
    "고가(20%) 평균가": "price_high_20",
    "중가(60%) 평균가": "price_mid_60",
    "저가(20%) 평균가": "price_low_20",
    "중간가(원/kg)": "price_median_kg",
    "최저가(원/kg)": "price_min_kg",
    "최고가(원/kg)": "price_max_kg",
    "경매 건수": "auction_cnt",
    "전순 평균가격(원) PreVious SOON": "baseline_prev_period",
    "전달 평균가격(원) PreVious MMonth": "baseline_prev_month",
    "전년 평균가격(원) PreVious YeaR": "baseline_prev_year",
    "평년 평균가격(원) Common Year SOON": "baseline_common_year",
    "연도": "year"
}
```

---

## E. API 입력 형태

### A) 자연어
```json
{"question": "감자 수미, 최근 6개월 가격 추세 보여줘"}
```

### B) 필터 직접 지정
```json
{"filters": {...}}
```

### C) Clarification 답변
```json
{
  "question": "원 질문",
  "clarify_answers": {
    "expensive_meaning": "high_avg_price",
    "recent_window": "30d"
  }
}
```

---

## F. 테스트 케이스 (5개)

1. "감자 수미, 최근 6개월 가격 추세 보여줘"
2. "양파, 전국도매시장, 2019년 가격과 반입량 같이 보여줘"
3. "배추, 최근 3개월 변동성(급등락) 큰 구간 알려줘"
4. "마늘, 시장별 비교해줘(상위 5개 시장)"
5. "대파, 최근 한달 가격이 전월 대비 얼마나 올랐어?"

---

## G. 환경변수

```
DATA_PATH=/var/task/data/sample_agri_prices.csv
BEDROCK_MODEL_ID=amazon.titan-text-express-v1
AWS_REGION=ap-southeast-2
```

---

## H. 한계 및 다음 개선

- S3+Athena로 확장
- 기상/환율 데이터 추가
- 더 정교한 품목/품종 매칭 (형태소 분석)
- 다중 품목 비교 기능
