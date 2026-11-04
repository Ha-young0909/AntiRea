"""Streamlit 비교 화면 — feat/ui-compare에서 구현한다.

레이아웃:
  좌: 원본 코드 / 우: 난독화된 코드
  하단: metrics.py 지표 + ai.py의 before&after 분석 점수

지금은 껍데기 시그니처만 알면 되므로 가짜 데이터로 먼저 레이아웃을 잡을 수 있다.
"""

from __future__ import annotations

import streamlit as st

from obfuscate import ObfuscationOptions, obfuscate_source

SAMPLE_PATH = "samples/target.py"


def load_sample(path: str = SAMPLE_PATH) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def render() -> None:
    st.set_page_config(page_title="Anti-REA: 난독화 비교", layout="wide")
    st.title("Anti-REA — 보호 전/후 비교")
    st.caption('"보호 전엔 코드가 술술 읽히는데, 난독화 후엔 막힌다"를 보여줍니다.')

    original = load_sample()

    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader("원본 (읽기 쉬움)")
        st.code(original, language="python")

    with col_right:
        st.subheader("난독화 후 (읽기 어려움)")
        try:
            obfuscated, report = obfuscate_source(original, ObfuscationOptions())
            st.code(obfuscated, language="python")
        except NotImplementedError:
            st.info("obfuscate.py가 feat/obfuscator-core에서 구현되면 여기에 표시됩니다.")

    st.divider()
    st.subheader("지표 & AI 분석 (before / after)")
    st.info("metrics.py / ai.py가 구현되면 여기에 before/after 수치와 점수를 표시합니다.")


if __name__ == "__main__":
    render()
