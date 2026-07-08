"""Pacote da API HTTP AzimeAI (FastAPI).

Substitui o frontend Streamlit (app.py). A lógica de domínio vive em `src/`
e é inteiramente reutilizada — este pacote só adiciona a camada HTTP
(gerenciamento de sessões, endpoints REST e streaming SSE).
"""
