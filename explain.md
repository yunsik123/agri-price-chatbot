# 농산물 가격 분석 AI 챗봇 - 프로젝트 보고서

## 1. 프로젝트 개요

### 1.1 프로젝트명
**AWS AI Service 기반 농산물(도매시장) 가격 분석·시각화 챗봇**

### 1.2 목적
전국 도매시장의 농산물 가격 데이터를 **자연어 질문**으로 분석하고, **시각화된 대시보드**와 **AI 분석 설명**을 제공하는 서버리스 웹 애플리케이션

### 1.3 주요 기능
| 기능 | 설명 |
|------|------|
| 자연어 질문 처리 | "감자 최근 6개월 가격 추세 보여줘" 같은 질문을 이해 |
| 데이터 시각화 | 가격/반입량 차트, 메트릭 카드 표시 |
| AI 분석 설명 | Bedrock Titan이 데이터 기반 분석 내러티브 생성 |
| 시장 비교 | 상위 N개 시장 가격 비교 |
| 변동성 분석 | 급등락 구간 탐지 및 시각화 |

### 1.4 기술 스택
```
Frontend : HTML5 + CSS3 + JavaScript + Plotly.js
Backend  : AWS Lambda (Python 3.10)
AI/ML    : Amazon Bedrock (Titan Text Express v1)
Infra    : S3 + API Gateway + Lambda (Serverless)
Data     : pandas + CSV (전국도매시장 가격 데이터)
```

---

## 2. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                      웹 브라우저                              │
│  ┌────────────────────┐   ┌────────────────────────────┐   │
│  │  📊 대시보드 (좌측)  │   │  💬 AI 채팅 (우측)          │   │
│  │  - 메트릭 카드      │   │  - 자연어 질문 입력         │   │
│  │  - 가격 추세 차트   │   │  - AI 응답 표시            │   │
│  │  - 반입량 막대 차트 │   │  - 예시 질문 버튼          │   │
│  └────────────────────┘   └────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              S3 (정적 웹사이트 호스팅)                        │
│                    index.html                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   API Gateway (HTTP API)                     │
│                    POST /api/query                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Lambda Function                           │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────────┐  │
│  │   NLU   │ → │  Query  │ → │Features │ → │  Narrative  │  │
│  │ 자연어   │   │ 데이터   │   │ 요약    │   │   AI 설명   │  │
│  │ 파싱    │   │ 조회    │   │ 계산    │   │   생성      │  │
│  └─────────┘   └─────────┘   └─────────┘   └─────────────┘  │
│                      │                            │          │
│              ┌───────▼───────┐           ┌───────▼───────┐  │
│              │   CSV 데이터   │           │    Bedrock    │  │
│              │  (Lambda 내장) │           │  (Titan LLM)  │  │
│              └───────────────┘           └───────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 폴더 구조 및 파일 설명

```
aws_agri/
│
├── 📁 frontend/                    # 프론트엔드 (웹 UI)
│   └── index.html                  # 메인 웹페이지 (대시보드 + 채팅)
│
├── 📁 src/                         # 핵심 비즈니스 로직
│   ├── __init__.py
│   ├── schema.py                   # Pydantic 스키마 정의
│   ├── data_loader.py              # CSV 데이터 로딩/전처리
│   ├── nlu.py                      # 자연어 → 필터 변환 (Bedrock)
│   ├── query.py                    # 데이터 조회/집계
│   ├── features.py                 # 요약 지표 계산 (WoW, MoM, 변동성)
│   └── narrative.py                # AI 분석 설명 생성 (Bedrock)
│
├── 📁 lambdas/agri_api/            # Lambda 배포용
│   ├── app.py                      # Lambda 핸들러 (진입점)
│   └── requirements.txt
│
├── 📁 streamlit_app/               # Streamlit 버전 (레거시)
│   └── app.py
│
├── 📁 data/                        # 데이터
│   └── sample_agri_prices.csv      # 전국도매시장 가격 데이터
│
├── 📁 tests/                       # 테스트 코드
│   ├── conftest.py
│   ├── test_schema.py
│   ├── test_data_loader.py
│   ├── test_query.py
│   ├── test_features.py
│   ├── test_nlu.py
│   └── test_e2e.py
│
├── 📄 local_server.py              # 로컬 개발 서버 (FastAPI)
├── 📄 deploy_aws.ps1               # AWS 배포 스크립트 (PowerShell)
├── 📄 deploy.ps1                   # SAM 배포 스크립트
├── 📄 deploy.sh                    # SAM 배포 스크립트 (Linux/Mac)
├── 📄 template.yaml                # AWS SAM 템플릿
├── 📄 requirements.txt             # Python 의존성
├── 📄 CLAUDE.md                    # 프로젝트 명세서
├── 📄 README.md                    # 프로젝트 소개
└── 📄 explain.md                   # 이 파일 (프로젝트 보고서)
```

---

## 4. 핵심 모듈 상세 설명

### 4.1 src/schema.py - 데이터 스키마
```python
# 사용자 질문에서 추출되는 필터 구조
FilterRequest:
  - item_name: str        # 품목명 (필수) - "감자", "사과", "배추" 등
  - variety_name: str     # 품종명 (선택) - "수미", "후지" 등
  - market_name: str      # 시장명 (선택) - 기본값 "전국도매시장"
  - date_from: str        # 시작일 (YYYY-MM-DD)
  - date_to: str          # 종료일 (YYYY-MM-DD)
  - chart_type: str       # 차트 유형 (trend/compare_markets/volatility)
  - granularity: str      # 집계 단위 (daily/weekly)
```

### 4.2 src/nlu.py - 자연어 이해
```
입력: "감자 수미, 최근 6개월 가격 추세 보여줘"
     ↓
  Bedrock Titan LLM
     ↓
출력: {
  "item_name": "감자",
  "variety_name": "수미",
  "date_from": "2024-06-27",
  "date_to": "2024-12-27",
  "chart_type": "trend"
}
```

### 4.3 src/query.py - 데이터 조회
| 함수 | 기능 |
|------|------|
| `query_trend()` | 시계열 가격 추세 조회 |
| `query_compare_markets()` | 시장별 비교 (Top N) |
| `query_volatility()` | 변동성 분석 |
| `apply_filters()` | 필터 조건 적용 |
| `aggregate_by_granularity()` | 일간/주간 집계 |

### 4.4 src/features.py - 요약 지표
| 지표 | 설명 |
|------|------|
| `latest_price` | 최근 가격 |
| `latest_volume` | 최근 반입량 |
| `wow_price_pct` | 전주 대비 가격 변화율 (%) |
| `mom_price_pct` | 전월 대비 가격 변화율 (%) |
| `volatility_14d` | 14일 변동성 (표준편차) |

### 4.5 src/narrative.py - AI 분석 설명
```
입력: 필터 + 시계열 데이터 + 요약 통계
     ↓
  Bedrock Titan LLM (프롬프트)
     ↓
출력: "감자 수미의 최근 6개월 가격을 분석한 결과,
      전반적으로 상승 추세를 보이고 있습니다..."
```

---

## 5. 데이터 흐름

```
1️⃣ 사용자 질문 입력
   "감자 최근 6개월 가격 보여줘"
          │
          ▼
2️⃣ API Gateway → Lambda 호출
   POST /api/query
   {"question": "감자 최근 6개월 가격 보여줘"}
          │
          ▼
3️⃣ NLU 모듈 (Bedrock Titan)
   자연어 → 구조화된 필터 JSON 변환
   {
     "item_name": "감자",
     "date_from": "2024-06-27",
     "date_to": "2024-12-27",
     "chart_type": "trend"
   }
          │
          ▼
4️⃣ Query 모듈 (pandas)
   CSV 데이터 필터링 & 집계
   → 시계열 데이터 생성
          │
          ▼
5️⃣ Features 모듈
   요약 통계 계산
   - 최근 가격: 2,315원/kg
   - 전주 대비: +5.2%
          │
          ▼
6️⃣ Narrative 모듈 (Bedrock Titan)
   AI 분석 설명 생성
          │
          ▼
7️⃣ 응답 반환
   {
     "type": "result",
     "series": [...],      # 차트 데이터
     "summary": {...},     # 요약 지표
     "narrative": "..."    # AI 설명
   }
          │
          ▼
8️⃣ 프론트엔드 렌더링
   - 왼쪽: 차트 + 메트릭 카드
   - 오른쪽: AI 응답 표시
```

---

## 6. 배포 정보

### 6.1 배포된 AWS 리소스

| 서비스 | 리소스명 | 설명 |
|--------|----------|------|
| **S3** | agri-chatbot-frontend-260893304786-prod | 정적 웹 호스팅 |
| **Lambda** | agri-bedrock-chat-prod | 백엔드 API (Python 3.10) |
| **API Gateway** | xqrsjykrnb | HTTP API 엔드포인트 |
| **Lambda Layer** | AWSSDKPandas-Python310 | pandas/numpy 라이브러리 |
| **Bedrock** | amazon.titan-text-express-v1 | LLM 모델 |

### 6.2 접속 URL

| 구분 | URL |
|------|-----|
| **웹사이트** | http://agri-chatbot-frontend-260893304786-prod.s3-website-ap-southeast-2.amazonaws.com |
| **API** | https://xqrsjykrnb.execute-api.ap-southeast-2.amazonaws.com/prod/api/query |

---

## 7. 로컬 실행 방법

### 7.1 환경 설정
```bash
# 1. 가상환경 생성
python -m venv venv
venv\Scripts\activate  # Windows

# 2. 의존성 설치
pip install -r requirements.txt

# 3. AWS 자격증명 설정
aws configure
```

### 7.2 로컬 서버 실행
```bash
# 방법 1: 배치 파일
run_local.bat

# 방법 2: 직접 실행
python local_server.py
```

### 7.3 접속
```
http://localhost:8000
```

---

## 8. API 사용 예시

### 8.1 자연어 질문
```bash
curl -X POST https://xqrsjykrnb.execute-api.ap-southeast-2.amazonaws.com/prod/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "감자 최근 6개월 가격 추세 보여줘"}'
```

### 8.2 응답 예시
```json
{
  "type": "result",
  "filters": {
    "item_name": "감자",
    "date_from": "2024-06-27",
    "date_to": "2024-12-27",
    "chart_type": "trend"
  },
  "series": [
    {"date": "2024-07-01", "price": 1850.5, "volume": 125000},
    {"date": "2024-07-08", "price": 1920.3, "volume": 118000},
    ...
  ],
  "summary": {
    "latest_price": 2315.53,
    "latest_volume": 98500,
    "wow_price_pct": 5.2,
    "mom_price_pct": 12.8,
    "volatility_14d": 145.2
  },
  "narrative": "감자의 최근 6개월 가격 추세를 분석한 결과..."
}
```

---

## 9. 핵심 설계 원칙

### 9.1 LLM 안전 사용
```
❌ LLM이 SQL을 직접 생성/실행하지 않음
✅ LLM은 "필터 JSON"만 출력
✅ 실제 데이터 조회는 서버 코드(pandas)가 수행
```

### 9.2 Clarification 처리
애매한 질문에 대해 확인 질문을 반환:
```
사용자: "감자 요즘 비싼 거 보여줘"
     ↓
챗봇: "'비싼'의 기준을 선택해주세요:
      - 평균가격이 높은
      - 가격 상승률이 큰
      - 변동성이 큰"
```

---

## 10. 테스트 케이스

| # | 질문 | 예상 결과 |
|---|------|----------|
| 1 | "감자 수미, 최근 6개월 가격 추세 보여줘" | trend 차트 + 수미 품종 필터 |
| 2 | "양파, 2019년 가격과 반입량 같이 보여줘" | volume_price 차트 |
| 3 | "배추, 최근 3개월 변동성 큰 구간 알려줘" | volatility 차트 |
| 4 | "마늘, 시장별 비교해줘(상위 5개 시장)" | compare_markets 차트 |
| 5 | "대파, 최근 한달 가격이 전월 대비 얼마나 올랐어?" | mom_price_pct 강조 |

---

## 11. 향후 개선 방향

| 항목 | 현재 | 개선 방향 |
|------|------|----------|
| 데이터 저장소 | CSV (Lambda 내장) | S3 + Athena |
| 데이터 갱신 | 수동 | 자동 파이프라인 |
| 품목 분석 | 단일 품목 | 다중 품목 비교 |
| 예측 기능 | 없음 | 시계열 예측 모델 |
| 외부 데이터 | 없음 | 기상/환율 연동 |

---

## 12. 작성 정보

- **작성일**: 2025-12-27
- **작성자**: Claude Code (Anthropic)
- **GitHub**: https://github.com/yunsik123/agri-price-chatbot
