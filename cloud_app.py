"""Streamlit Community Cloud entrypoint; local users keep using run.cmd."""
import hashlib
import runpy
from pathlib import Path
import streamlit as st

BASE=Path(__file__).resolve().parent


@st.cache_resource(show_spinner=False)
def prepare_demo(asset_revision):
    # Large model weights are omitted from GitHub and downloaded from a pinned,
    # checksum-verified public source only when this process initializes.
    runpy.run_path(str(BASE/"download_model.py"),run_name="__main__")
    from demo_data import add_examples
    add_examples()
    return True


revision=hashlib.sha256((BASE/"assets/demo_items.json").read_bytes()).hexdigest()
with st.spinner("첫 실행 준비 중입니다. AI 모델과 예시 물건을 불러오고 있습니다…"):
    try:
        prepare_demo(revision)
    except Exception:
        st.error("시연 준비를 완료하지 못했습니다. 잠시 후 다시 시도하거나 배포 로그를 확인해 주세요.")
        st.stop()

runpy.run_path(str(BASE/"app.py"),run_name="__main__")
