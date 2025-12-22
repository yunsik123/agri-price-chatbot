# AWS AI Service 기반 농산물 가격 분석·시각화 챗봇

본 프로젝트는 **AWS Managed AI Service와 Serverless 아키텍처**를 활용하여  
농산물 시계열 가격 데이터를 자연어로 질의하면  
**분석 → 시각화 → 해석까지 자동으로 제공하는 LLM 기반 챗봇 서비스**를 구현합니다.

LLM을 단순한 답변 생성기가 아니라  
**데이터 분석 파이프라인을 제어하는 오케스트레이터**로 활용하는 것을 핵심 목표로 합니다.

---

## 1. 프로젝트 개요 (Overview)

- 농산물 가격 데이터를 기반으로 한 **자연어 분석 챗봇**
- AWS Bedrock 기반 LLM을 **Serverless API**로 제공
- 시계열 데이터 분석 결과를 **Streamlit으로 시각화**
- RAG(Retrieval-Augmented Generation)를 통한 도메인 맥락 반영
- 운영·확장까지 고려한 **클라우드 AI 서비스 아키텍처 설계**

---

## 2. 주요 기능 (Key Features)

### 자연어 기반 분석 질의
- “최근 양파 가격 추세를 요약해줘”
- “마늘 가격 변동성이 컸던 시점은 언제야?”
- “계절성 영향을 고려하면 최근 가격 패턴은 어떠해?”

### 시계열 데이터 분석
- 가격 추세 분석
- 변동성(Volatility) 파악
- 이상 구간 탐지

### 자동 시각화
- 시간별 가격 라인 차트
- 주요 변동 구간 강조 표시
- 분석 결과와 해석을 한 화면에서 제공

### LLM 기반 해석
- 수치 기반 분석 결과를 자연어로 요약
- 데이터 부족 시 과장 없이 한계 명시

---

## 3. 시스템 아키텍처 (Architecture)

```
User
↓
API Gateway
↓
AWS Lambda (LLM Orchestrator)
↓
AWS Bedrock (LLM)
↓
S3 / Athena (농산물 시계열 데이터)
↓
OpenSearch (Vector DB, RAG)
↓
Streamlit UI (Visualization)
↓
ECS (Fargate) Hosting
```

---

## 4. RAG 설계 (Retrieval-Augmented Generation)

- OpenSearch Vector DB 기반 벡터 검색
- 농산물 **품목 정보, 유통 단계, 계절성 메타데이터** 임베딩
- 데이터 맥락을 함께 제공하여 응답 신뢰도 강화
- 단순 통계 결과가 아닌 **도메인 이해 기반 응답** 생성

---

## 5. 기술 스택 (Tech Stack)

### Cloud / Infrastructure
- AWS Bedrock
- AWS Lambda
- API Gateway (HTTP API)
- Amazon S3
- Amazon Athena
- Amazon ECS (Fargate)
- AWS IAM
- AWS CLI

### AI / ML
- Large Language Models (Claude / LLaMA via Bedrock)
- Prompt Engineering
- Embedding-based Retrieval (RAG)

### Data
- 농산물 시계열 가격 데이터 (CSV)
- SQL (Athena)

### Backend
- Python
- Boto3

### Frontend
- Streamlit

### Automation
- MCP 기반 Agent 설계
- AWS CLI를 활용한 배포·운영 자동화

---

## 6. 레포지토리 구조 (Repository Structure)

```
agri-price-chatbot/
├─ data/           # 농산물 시계열 데이터
├─ backend/
│  └─ lambda/      # Bedrock + Lambda 기반 API
├─ app/            # Streamlit UI
├─ infra/          # AWS CLI 기반 인프라 스크립트
├─ requirements.txt
└─ README.md
```

---

## 7. 배포 및 운영 (Deployment & Operation)

- **Serverless API**
  - Lambda + API Gateway를 통한 외부 호출 API 제공
- **서비스 호스팅**
  - Streamlit 애플리케이션을 ECS(Fargate) 환경에 컨테이너 배포
- **운영 자동화**
  - MCP + AWS CLI를 활용한 배포, 스케일링, 운영 작업 자동화 실험

---

## 8. 프로젝트 목표 (Project Goal)

- AWS Managed AI Service를 활용한 **실전형 AI 서비스 구현**
- LLM과 데이터 분석을 결합한 **의사결정 지원 도구 개발**
- PoC를 넘어 **운영 가능한 AI 아키텍처 경험 축적**

---

## 9. 현재 상태 (Status)

- MVP 개발 진행 중
- Serverless API 및 Streamlit UI 1차 구현 완료
- RAG 및 운영 자동화 기능 단계적 확장 예정

---

## Author

- **Yunsik Shin**
- GitHub: https://github.com/yunsik123