import streamlit as st
import requests

API_URL = "http://localhost:8000/chat"  # 나중에 API Gateway URL로 교체

st.title("농산물 가격 분석 챗봇 (AWS LLM)")

question = st.text_input("질문", "양파 가격 추세를 요약해줘")

if st.button("분석 요청"):
    response = requests.post(API_URL, json={
        "question": question,
        "rows": [
            ["2025-01-01", "onion", 1200],
            ["2025-01-02", "onion", 1180],
            ["2025-01-03", "onion", 1350],
        ]
    })
    st.write(response.json()["analysis"])