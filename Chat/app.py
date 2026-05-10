"""
app.py
Data Agent — Chatbot BI com Text-to-SQL, Análise e Dashboard
Entry point do Streamlit.
"""

import sys
import os

# Garante que os módulos locais sejam encontrados
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st

# ── Configuração da página (DEVE ser o primeiro comando Streamlit) ──────────
st.set_page_config(
    page_title="Data Agent",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get help": None,
        "Report a bug": None,
        "About": "**Data Agent PoC** · Powered by Groq + LLaMA 3.3 · v1.0"
    }
)

from components.sidebar import render_sidebar
config = render_sidebar()

