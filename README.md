# AWS AI Service 기반 농산물 가격 분석·시각화 챗봇

AWS Bedrock (Titan) + Serverless 아키텍처를 활용한 농산물 도매시장 가격 분석 챗봇입니다.

## 주요 기능

- 자연어 질문 → 구조화된 필터 JSON 변환 (LLM 기반)
- 도매시장 시계열 데이터 조회 및 집계
- 가격/반입량 추세, 시장별 비교, 변동성 분석
- WoW/MoM/변동성 등 요약 지표 자동 계산
- 규칙 기반 빠른 분석 설명 생성 (LLM 호출 최소화로 응답 속도 개선)
- XGBoost 기반 3개월 가격 예측
- 웹 대시보드로 시각화 (Split-panel: 대시보드 + AI 채팅)

## 아키텍처

```
User (자연어 질문)
     │
     ▼
┌─────────────────────────────────────────────┐
│           API Gateway (HTTP API)             │
└─────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────┐
│              AWS Lambda                      │
│  ┌─────────────────────────────────────┐    │
│  │ NLU: 자연어 → Filter JSON (Nova)    │    │
│  ├─────────────────────────────────────┤    │
│  │ Query: 필터 → 데이터 조회/집계       │    │
│  ├─────────────────────────────────────┤    │
│  │ Features: 요약 지표 계산            │    │
│  ├─────────────────────────────────────┤    │
│  │ Narrative: 규칙 기반 빠른 설명 생성  │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
     │                    │
     ▼                    ▼
┌──────────────┐   ┌──────────────────┐
│ Bedrock      │   │ CSV 데이터        │
│ (Nova Micro) │   │ (전국도매 가격)    │
└──────────────┘   └──────────────────┘
     │
     ▼
┌─────────────────────────────────────────────┐
│    S3 정적 웹호스팅 (Split-panel UI)          │
│  ┌────────────────┐  ┌──────────────────┐  │
│  │ 대시보드 (좌측) │  │ AI 채팅 (우측)   │  │
│  │ - 메트릭 카드   │  │ - 자연어 질문    │  │
│  │ - 가격/반입량   │  │ - 응답 표시      │  │
│  │ - 3개월 예측    │  │ - Clarification  │  │
│  └────────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────┘
```

## 핵심 원칙

1. **LLM은 SQL을 생성/실행하지 않음** - 필터 JSON만 출력
2. **데이터 조회는 서버 코드가 수행** - 안전하고 예측 가능
3. **애매한 질문은 Clarification으로 처리** - 사용자에게 확인

## 프로젝트 구조

```
aws_agri/
├── CLAUDE.md              # 프로젝트 명세서
├── README.md              # 이 파일
├── requirements.txt       # Python 의존성
├── template.yaml          # AWS SAM 템플릿
├── samconfig.toml         # SAM CLI 설정
├── deploy.ps1             # Windows 배포 스크립트
├── deploy.sh              # Linux/Mac 배포 스크립트
├── local_server.py        # 로컬 개발 서버 (FastAPI)
├── run_local.bat          # 로컬 서버 실행 스크립트
├── data/
│   ├── sample_agri_prices.csv  # 전국도매 가격 데이터
│   └── forecast_results.csv    # XGBoost 예측 결과
├── scripts/
│   └── local_forecast.py       # XGBoost 예측 + S3 업로드
├── src/
│   ├── __init__.py
│   ├── schema.py          # Pydantic 스키마
│   ├── data_loader.py     # CSV 로딩/매핑
│   ├── nlu.py             # 자연어 → 필터 변환
│   ├── query.py           # 데이터 조회/집계
│   ├── features.py        # 요약 지표 계산
│   └── narrative.py       # 분석 설명 생성
├── frontend/
│   └── index.html         # 웹 프론트엔드 (대시보드 + 채팅)
├── lambdas/agri_api/
│   ├── app.py             # Lambda 핸들러
│   └── requirements.txt
├── streamlit_app/
│   └── app.py             # Streamlit 대시보드 (레거시)
└── tests/
    ├── conftest.py
    ├── test_schema.py
    ├── test_data_loader.py
    ├── test_query.py
    ├── test_features.py
    ├── test_nlu.py
    └── test_e2e.py
```

## 로컬 실행

### 1. 환경 설정

```bash
# 가상환경 생성
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# AWS 자격증명 설정
aws configure  # 또는 환경변수 설정
```

### 2. 로컬 서버 실행 (권장)

```bash
# Windows
run_local.bat

# 또는 직접 실행
python local_server.py
```

브라우저에서 `http://localhost:8000` 접속

- **왼쪽**: 시각화 대시보드 (가격/반입량 차트, 메트릭 카드)
- **오른쪽**: AI 채팅 인터페이스

### 3. Streamlit 실행 (레거시)

```bash
cd streamlit_app
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속

### 4. 테스트 실행

```bash
pytest tests/ -v
```

## AWS 배포 (SAM)

AWS SAM을 사용하여 전체 스택을 자동 배포합니다:
- **S3**: 프론트엔드 정적 호스팅
- **CloudFront**: CDN + HTTPS
- **API Gateway**: REST API
- **Lambda**: 백엔드 로직

### 사전 요구사항

```bash
# AWS SAM CLI 설치
# https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html

# AWS CLI 설정
aws configure
```

### 원클릭 배포

```powershell
# Windows PowerShell
.\deploy.ps1 -Stage prod -Region ap-southeast-2
```

```bash
# Linux/Mac
chmod +x deploy.sh
./deploy.sh prod ap-southeast-2
```

### 단계별 배포

```bash
# 1. SAM 빌드
sam build --template template.yaml

# 2. SAM 배포
sam deploy --guided

# 3. 프론트엔드 업로드 (배포 스크립트가 자동 처리)
aws s3 sync frontend/ s3://<BUCKET_NAME>/
```

### 배포 결과

배포 완료 후 출력되는 CloudFront URL로 접속:
```
https://d1234567890.cloudfront.net
```

### AWS CLI 직접 배포 (권장)

SAM CLI 호환성 문제 시 AWS CLI로 직접 배포합니다.

```bash
# 1. 배포 패키지 생성
mkdir -p deploy_package/src deploy_package/data
cp lambdas/agri_api/app.py deploy_package/
cp src/*.py deploy_package/src/
cp data/sample_agri_prices.csv deploy_package/data/

# 2. pydantic 의존성 설치 (Lambda용)
pip install pydantic python-dateutil -t deploy_package/ \
    --platform manylinux2014_x86_64 --python-version 3.10 --only-binary :all:

# 3. zip 패키징 및 Lambda 업데이트
cd deploy_package && zip -r ../lambda.zip . && cd ..
aws lambda update-function-code \
    --function-name agri-bedrock-chat-prod \
    --zip-file fileb://lambda.zip \
    --region ap-southeast-2

# 4. 프론트엔드 S3 업로드
aws s3 cp frontend/index.html \
    s3://agri-chatbot-frontend-260893304786-prod/index.html \
    --region ap-southeast-2 \
    --content-type "text/html; charset=utf-8"

# 5. 정리
rm -rf deploy_package lambda.zip
```

> **주의**: 프론트엔드의 `API_ENDPOINT`가 절대 URL로 설정되어 있어야 S3 호스팅에서 정상 작동합니다.

## API 사용법

### 요청 형태

#### A) 자연어 질문
```json
POST /query
{
    "question": "감자 수미, 최근 6개월 가격 추세 보여줘"
}
```

#### B) 필터 직접 지정
```json
POST /query
{
    "filters": {
        "item_name": "감자",
        "variety_name": "수미",
        "date_from": "2024-01-01",
        "date_to": "2024-06-30",
        "chart_type": "trend"
    }
}
```

#### C) Clarification 답변
```json
POST /query
{
    "question": "감자 요즘 비싼 거",
    "clarify_answers": {
        "expensive_meaning": "high_avg_price",
        "recent_window": "30d"
    }
}
```

### 응답 형태

#### Result 응답
```json
{
    "type": "result",
    "filters": {
        "item_name": "감자",
        "variety_name": "수미",
        ...
    },
    "series": [
        {"date": "2024-01-05", "price": 1500.0, "volume": 10000.0, "market_name": null},
        ...
    ],
    "summary": {
        "latest_price": 1800.0,
        "latest_volume": 12000.0,
        "wow_price_pct": 5.2,
        "mom_price_pct": 12.5,
        "volatility_14d": 150.3,
        "data_points": 24,
        "missing_rate": 0.0
    },
    "narrative": "감자 수미의 최근 6개월 가격 추세를 분석한 결과...",
    "warnings": [],
    "clarification": null,
    "request_id": "uuid-here"
}
```

#### Clarify 응답
```json
{
    "type": "clarify",
    "filters": null,
    "series": [],
    "summary": null,
    "narrative": "",
    "warnings": ["질문이 애매하여 확인이 필요합니다."],
    "clarification": {
        "draft_filters": {"item_name": "감자"},
        "questions": [
            {
                "id": "expensive_meaning",
                "question": "'비싼'의 기준을 선택해주세요:",
                "options": ["high_avg_price", "high_price_change", "high_volatility"],
                "default": "high_avg_price"
            }
        ]
    },
    "request_id": "uuid-here"
}
```

## 예시 curl

```bash
# 자연어 질문
curl -X POST https://<API_ID>.execute-api.ap-southeast-2.amazonaws.com/prod/query \
    -H "Content-Type: application/json" \
    -d '{"question": "감자 수미, 최근 6개월 가격 추세 보여줘"}'

# 필터 직접 지정
curl -X POST https://<API_ID>.execute-api.ap-southeast-2.amazonaws.com/prod/query \
    -H "Content-Type: application/json" \
    -d '{"filters": {"item_name": "양파", "date_from": "2019-01-01", "date_to": "2019-12-31", "chart_type": "trend"}}'

# 시장 비교
curl -X POST https://<API_ID>.execute-api.ap-southeast-2.amazonaws.com/prod/query \
    -H "Content-Type: application/json" \
    -d '{"question": "마늘, 시장별 비교해줘(상위 5개 시장)"}'
```

## 테스트 케이스

| 질문 | 예상 결과 |
|------|----------|
| "감자 수미, 최근 6개월 가격 추세 보여줘" | trend 차트 + 수미 품종 필터 |
| "양파, 전국도매시장, 2019년 가격과 반입량 같이 보여줘" | volume_price 차트 + 2019년 필터 |
| "배추, 최근 3개월 변동성(급등락) 큰 구간 알려줘" | volatility 차트 |
| "마늘, 시장별 비교해줘(상위 5개 시장)" | compare_markets 차트 |
| "대파, 최근 한달 가격이 전월 대비 얼마나 올랐어?" | mom_price_pct 강조 |

## 운영 체크리스트

- [ ] Lambda 메모리/타임아웃 설정 (권장: 512MB, 20초)
- [ ] Bedrock 모델 접근 권한 확인
- [ ] CloudWatch 로그 모니터링 설정
- [ ] API Gateway 스로틀링 설정
- [ ] 데이터 갱신 파이프라인 구축 (S3 → Lambda 트리거)

## 한계 및 개선 방향

### 현재 한계
- CSV 파일 기반으로 대용량 데이터 처리 제한
- 실시간 데이터 반영 불가
- 단일 품목 분석만 지원

### 개선 방향
- S3 + Athena 연동으로 대용량 데이터 지원
- 기상/환율 데이터 추가로 분석 고도화
- 다중 품목 비교 기능
- 예측 모델 통합
- RAG 기반 도메인 지식 강화

## 라이선스

MIT License

## Author

**Yunsik Shin**
- GitHub: https://github.com/yunsik123
