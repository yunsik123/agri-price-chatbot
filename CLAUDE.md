# AWS AI Service 기반 농산물(도매시장) 가격 분석·시각화 챗봇

## 프로젝트 개요
- **리전**: ap-southeast-2
- **Bedrock 모델**: amazon.nova-micro-v1:0 (Amazon Nova Micro)
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
│  │(Bedrock) │  │(pandas)  │  │(summary) │  │  (규칙 기반)      │ │
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
│                   (Amazon Nova Micro)                            │
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
│   └── narrative.py        # 규칙 기반 빠른 설명 생성 (LLM 호출 스킵)
├── scripts/
│   └── local_forecast.py   # XGBoost 예측 + S3 업로드
├── streamlit_app/
│   └── app.py              # Streamlit 대시보드 (레거시)
├── tests/                  # pytest 테스트
├── data/
│   ├── sample_agri_prices.csv    # 원본 가격 데이터
│   └── forecast_results.csv      # 예측 결과
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
BEDROCK_MODEL_ID=amazon.nova-micro-v1:0
AWS_REGION=ap-southeast-2
```

---

## H. 주요 기능 및 최적화

### 응답 속도 최적화
- Narrative 생성 시 LLM 호출 스킵 → 규칙 기반 빠른 응답
- NLU에만 LLM 사용 (필터 추출), 설명은 규칙 기반 생성
- 예상 응답 시간: 1-3초 (기존 4-10초에서 개선)

### 대시보드 UX
- 제목 옆에 오늘 날짜 표시
- 기본값 메시지에 실제 기간 표시 (예: "최근 90일: 2019-07-05 ~ 2019-10-05")
- 3개월 가격 예측 차트 및 요약 테이블

### 가격 예측 (XGBoost)
- scripts/local_forecast.py 실행 → data/forecast_results.csv 생성
- S3에 업로드하여 Lambda에서 조회

---

## I. AWS 배포 방법 (AWS CLI 직접 사용)

SAM CLI가 Python 버전 호환 문제가 있을 경우, AWS CLI로 직접 배포합니다.

### Lambda 배포

```bash
# 1. 배포 패키지 디렉토리 생성
mkdir -p deploy_package/src deploy_package/data

# 2. 코드 복사
cp lambdas/agri_api/app.py deploy_package/
cp src/*.py deploy_package/src/
cp data/sample_agri_prices.csv deploy_package/data/

# 3. pydantic 의존성 설치 (Lambda용 Linux 빌드)
pip install pydantic python-dateutil -t deploy_package/ --platform manylinux2014_x86_64 --python-version 3.10 --only-binary :all:

# 4. zip 패키징
cd deploy_package && zip -r ../lambda.zip . && cd ..

# 5. Lambda 업데이트
aws lambda update-function-code \
    --function-name agri-bedrock-chat-prod \
    --zip-file fileb://lambda.zip \
    --region ap-southeast-2

# 6. 정리
rm -rf deploy_package lambda.zip
```

### 프론트엔드 배포

```bash
# S3에 업로드 (UTF-8 인코딩 명시)
aws s3 cp frontend/index.html \
    s3://agri-chatbot-frontend-260893304786-prod/index.html \
    --region ap-southeast-2 \
    --content-type "text/html; charset=utf-8"
```

### 주의사항

1. **프론트엔드 API 엔드포인트**: S3 호스팅 시 절대 URL 필요
   ```javascript
   // frontend/index.html 626번 줄
   const API_ENDPOINT = 'https://xqrsjykrnb.execute-api.ap-southeast-2.amazonaws.com/prod/api/query';
   ```

2. **Lambda 의존성**: AWSSDKPandas Layer에 pydantic이 없으므로 직접 패키징 필요

3. **인코딩 주의**: Windows에서 PowerShell로 파일 수정 시 UTF-8 인코딩 깨질 수 있음 → Python 사용 권장

---

## J. 한계 및 다음 개선

- S3+Athena로 확장
- 기상/환율 데이터 추가
- 더 정교한 품목/품종 매칭 (형태소 분석)
- 다중 품목 비교 기능
