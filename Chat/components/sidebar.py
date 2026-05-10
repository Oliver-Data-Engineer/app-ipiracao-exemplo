"""
components/sidebar.py
Sidebar de configurações: seleção de DB, tabelas, modelo e API Key.
"""

from dotenv import load_dotenv
import streamlit as st
import os

from modules.AthenaManager import AthenaManager


athena_conn = AthenaManager()


def _init_session_state() -> None:
    load_dotenv()
    defaults = {
        "groq_api_key": os.getenv("GROQ_API_KEY", ""),
        "aws_access_key_id": os.getenv("aws_access_key_id", ""),
        "aws_secret_access_key": os.getenv("aws_secret_access_key", ""),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _render_ai_settings() -> tuple[str, float]:
    with st.expander("⚙️ Configurações de IA", expanded=False):
        api_key = st.text_input(
            "GROQ API Key",
            value=st.session_state.get("groq_api_key", ""),
            type="password",
            placeholder="gsk_...",
            help="Configure em .env ou insira aqui"
        )
        if api_key:
            st.session_state["groq_api_key"] = api_key
            os.environ["GROQ_API_KEY"] = api_key

        modelo = st.selectbox(
            "Modelo",
            ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "mixtral-8x7b-32768"],
            help="Modelo Groq para geração de SQL e análises"
        )
        temperatura = st.slider(
            "Temperatura (SQL)",
            min_value=0.0, max_value=1.0, value=0.0, step=0.1,
            help="0 = preciso (recomendado para SQL), 1 = criativo"
        )
    return modelo, temperatura


def _render_aws_settings() -> None:
    with st.expander("⚙️ Ambiente de AWS", expanded=False):
        access_key = st.text_input(
            "Access Key",
            value=st.session_state.get("aws_access_key_id", ""),
            type="password",
            placeholder="AKIA...",
            help="Configure em .env ou insira aqui"
        )
        if access_key:
            st.session_state["aws_access_key_id"] = access_key
            os.environ["aws_access_key_id"] = access_key

        secret_key = st.text_input(
            "Secret Key",
            value=st.session_state.get("aws_secret_access_key", ""),
            type="password",
            placeholder="...",
            help="Configure em .env ou insira aqui"
        )
        if secret_key:
            st.session_state["aws_secret_access_key"] = secret_key
            os.environ["aws_secret_access_key"] = secret_key


def _render_db_selector(dbs: list[str]) -> str:
    st.markdown("##### 🗄️ Banco de Dados")
    saved = st.session_state.get("database", dbs[0])
    idx = dbs.index(saved) if saved in dbs else 0
    db_selecionado = st.selectbox(
        "Selecione o banco",
        dbs,
        index=idx,
        label_visibility="collapsed"
    )
    st.session_state["database"] = db_selecionado
    return db_selecionado


def _render_table_selector(db: str) -> tuple[str, dict]:
    st.markdown("##### 📋 Tabelas")
    tabelas = athena_conn.list_tables(db=db)

    if not tabelas:
        st.warning("Nenhuma tabela encontrada.")
        return "", {}

    tabela_nomes = list(tabelas.keys())
    saved = st.session_state.get("tabelas_selecionadas", tabela_nomes[0])
    idx = tabela_nomes.index(saved) if saved in tabela_nomes else 0

    tabela_selecionada = st.selectbox(
        "Selecione a tabela",
        tabela_nomes,
        index=idx,
        label_visibility="collapsed"
    )
    st.session_state["tabelas_selecionadas"] = tabela_selecionada
    return tabela_selecionada, tabelas


def render_sidebar() -> dict:
    """
    Renderiza a sidebar e retorna o contexto de configuração atual.

    Returns:
        dict com: database, tabelas_selecionadas, schema, api_key, modelo, temperatura
    """
    with st.sidebar:
        st.markdown("""
        <div style='text-align:center; padding: 12px 0 20px 0;'>
            <div style='font-size:2rem;'>🧠</div>
            <div style='font-size:1.15rem; font-weight:700; color:#E8F4FD; letter-spacing:0.03em;'>Data Agent</div>
            <div style='font-size:0.72rem; color:#94a3b8; margin-top:2px; letter-spacing:0.08em;'>BI · SQL · Analytics</div>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        _init_session_state()
        modelo, temperatura = _render_ai_settings()
        _render_aws_settings()

        st.divider()

        dbs = athena_conn.list_databases()
        db_selecionado = _render_db_selector(dbs)
        tabela_selecionada, tabelas = _render_table_selector(db_selecionado)
        schema = tabelas.get(tabela_selecionada, {})

        return {
            "database": db_selecionado,
            "tabelas_selecionadas": tabela_selecionada,
            "schema": schema,
            "api_key": st.session_state.get("groq_api_key", ""),
            "modelo": modelo,
            "temperatura": temperatura,
        }
