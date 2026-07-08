"""Gerenciador de sessões in-memory, thread-safe.

Espelha o `st.session_state` que vivia em app.py (Streamlit), porém:
- Cada sessão tem seu próprio grafo LangGraph compilado (e portanto seu
  próprio MemorySaver) — necessário para HITL/resume isolado entre sessões.
- Um `threading.RLock` por sessão serializa mutações concorrentes
  (upload + process + hitl/resolve sobre a mesma sessão).
- Sessões expiram após `TTL_SECONDS` de inatividade (GC em background).

Tudo é in-memory: estado se perde em redeploy/restart. Adequado para
single-replica. Para multi-replica/durável, trocar por SqliteSaver/
PostgresSaver (ver plano Fase 2).
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Tempo de vida de uma sessão ociosa antes do GC poder removê-la.
TTL_SECONDS = 4 * 60 * 60  # 4 h


@dataclass
class SessionState:
    """Estado de uma sessão de processamento (uma invoice → um PC).

    Campos espelham o `_DEFAULTS` de app.py. O grafo é lazy (criado no
    primeiro `/process/start`) porque depende do perfil/material.
    """

    session_id: str
    thread_id: str  # uuid4 — chave do checkpointer do LangGraph
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    stage: str = "init"  # init|config|ready|processing|hitl|done
    df_limpo: Optional[pd.DataFrame] = None
    perfil: Optional[dict] = None
    tipo_material: Optional[str] = None
    nome_arquivo: str = ""
    marca: str = "AL"
    cod_fornecedor: str = ""
    grafo: Any = None  # compilar_grafo() lazy
    config: dict = field(default_factory=dict)  # {"configurable": {"thread_id"}}
    ultima_saida: Optional[dict] = None
    ultima_interrupcao: Any = None
    chat_historico: list[dict] = field(default_factory=list)
    _aneis_revisados: dict = field(default_factory=dict)
    pc_confirmado: bool = False
    erro_processamento: Optional[str] = None

    def touch(self) -> None:
        self.last_active = time.time()


class SessionManager:
    """Registry de sessões concorrentes, com lock global fino (por sessão).

    Um lock por session_id evita que, p.ex., dois requests `/hitl/resolve`
    simultâneos sobre a mesma sessão corrompam o estado do grafo. Sessões
    distintas rodam livremente em paralelo (cada uma no seu thread_id /
    MemorySaver).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._registry_lock = threading.Lock()
        self._stop_gc = threading.Event()
        self._gc_thread = threading.Thread(
            target=self._gc_loop, name="session-gc", daemon=True
        )
        self._gc_thread.start()

    # ── criação / acesso ──────────────────────────────────────────

    def criar(self) -> SessionState:
        """Cria uma nova sessão e retorna seu estado inicial."""
        sid = uuid.uuid4().hex
        st = SessionState(
            session_id=sid,
            thread_id=str(uuid.uuid4()),
        )
        st.config = {"configurable": {"thread_id": st.thread_id}}
        with self._registry_lock:
            self._sessions[sid] = st
            self._locks[sid] = threading.RLock()
        logger.info("Sessão criada: %s (thread %s)", sid, st.thread_id)
        return st

    def get(self, session_id: str) -> Optional[SessionState]:
        with self._registry_lock:
            st = self._sessions.get(session_id)
            if st is not None:
                st.touch()
            return st

    def require(self, session_id: str) -> SessionState:
        """Get ou 404-like. Caller decide como tratar None."""
        st = self.get(session_id)
        if st is None:
            raise KeyError(session_id)
        return st

    def lock_for(self, session_id: str) -> threading.RLock:
        """Lock recursivo associado à sessão (para serializar mutações)."""
        with self._registry_lock:
            lk = self._locks.get(session_id)
            if lk is None:
                lk = threading.RLock()
                self._locks[session_id] = lk
            return lk

    # ── reset / remoção ───────────────────────────────────────────

    def reset(self, session_id: str) -> Optional[SessionState]:
        """Reseta o estado de processo mas mantém o session_id.

        Gera nova thread_id (novo MemorySaver efetivo) — equivalente ao
        `_reset_session()` do app.py seguido de nova thread.
        """
        with self.lock_for(session_id):
            st = self.get(session_id)
            if st is None:
                return None
            st.thread_id = str(uuid.uuid4())
            st.config = {"configurable": {"thread_id": st.thread_id}}
            st.stage = "init"
            st.df_limpo = None
            st.perfil = None
            st.tipo_material = None
            st.nome_arquivo = ""
            st.grafo = None
            st.ultima_saida = None
            st.ultima_interrupcao = None
            st.chat_historico = []
            st._aneis_revisados = {}
            st.pc_confirmado = False
            st.erro_processamento = None
            st.touch()
            logger.info("Sessão resetada: %s (nova thread %s)",
                        session_id, st.thread_id)
            return st

    def drop(self, session_id: str) -> None:
        with self._registry_lock:
            self._sessions.pop(session_id, None)
            self._locks.pop(session_id, None)

    # ── GC de sessões ociosas ─────────────────────────────────────

    def _gc_loop(self) -> None:
        while not self._stop_gc.wait(60 * 5):  # a cada 5 min
            self._collect_expired()

    def _collect_expired(self) -> None:
        agora = time.time()
        expiradas = [
            sid for sid, st in self._sessions.items()
            if agora - st.last_active > TTL_SECONDS
        ]
        for sid in expiradas:
            self.drop(sid)
            logger.info("Sessão expirada removida: %s", sid)

    def shutdown(self) -> None:
        self._stop_gc.set()


# Singleton importável por todo o pacote.
sessions = SessionManager()
