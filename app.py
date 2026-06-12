"""FitBot — assistente virtual do FIT IT (fitit.pt).

Streamlit chat UI with FIT IT branding, routed RAG retrieval, conversation
memory and a background scheduler that keeps the class schedule fresh.
"""

from datetime import datetime

import streamlit as st
from streamlit.components.v1 import html as components_html

st.set_page_config(
    page_title="FitBot · FIT IT",
    page_icon="💪",
    layout="centered",
    initial_sidebar_state="expanded",
)

from src.config import BRAND, CONTACT_URL
from src import generation, retrieval, updater, vectorstore
from src.scheduler import next_run_times, start_scheduler

# ---------------------------------------------------------------------------
# Styling (FIT IT brand: gold #daa360, purple #58449a on near-black)
# ---------------------------------------------------------------------------

CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, .stApp, [data-testid="stSidebar"] {{
    font-family: 'Inter', -apple-system, sans-serif;
}}
.stApp {{
    background:
        radial-gradient(1100px 520px at 15% -10%, rgba(88,68,154,.28), transparent 60%),
        radial-gradient(900px 480px at 110% 5%, rgba(218,163,96,.14), transparent 55%),
        {BRAND['dark']};
    color: {BRAND['text']};
}}
header[data-testid="stHeader"] {{ background: transparent; }}
#MainMenu, footer {{ visibility: hidden; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 7rem; max-width: 780px; }}

/* ---- hero ---- */
.fitbot-hero {{ text-align: center; margin-bottom: .6rem; }}
.fitbot-hero .logo {{
    font-size: 2.3rem; font-weight: 800; letter-spacing: .14em;
    background: linear-gradient(110deg, {BRAND['gold']} 25%, {BRAND['purple']} 90%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
}}
.fitbot-hero .tag {{
    display: inline-block; margin-top: .35rem; padding: .28rem .9rem;
    border: 1px solid rgba(218,163,96,.35); border-radius: 999px;
    color: {BRAND['muted']}; font-size: .8rem; letter-spacing: .06em;
}}

/* ---- chat bubbles ---- */
[data-testid="stChatMessage"] {{
    background: transparent; border: none; padding: 0; gap: 0;
    margin-bottom: .35rem;
}}
[data-testid="stChatMessage"] [data-testid^="stChatMessageAvatar"] {{ display: none; }}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) > div:last-child {{
    background: {BRAND['card']};
    border: 1px solid rgba(218,163,96,.22);
    border-radius: 16px 16px 16px 4px;
    padding: .9rem 1.15rem; margin-right: 14%;
    box-shadow: 0 4px 18px rgba(0,0,0,.25);
}}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) > div:last-child {{
    background: linear-gradient(135deg, {BRAND['gold']}, {BRAND['gold_dark']});
    border-radius: 16px 16px 4px 16px;
    padding: .9rem 1.15rem; margin-left: 18%;
    box-shadow: 0 4px 18px rgba(218,163,96,.18);
}}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) p,
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) li {{
    color: #1b1610 !important; font-weight: 600;
}}
[data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li {{
    color: {BRAND['text']}; font-size: .95rem; line-height: 1.55;
}}

/* ---- typing indicator ---- */
.typing-dots {{ display: inline-flex; gap: 7px; padding: 4px 2px; }}
.typing-dots span {{
    width: 9px; height: 9px; border-radius: 50%;
    background: {BRAND['gold']};
    animation: fitb-bounce 1.2s infinite ease-in-out;
}}
.typing-dots span:nth-child(2) {{ animation-delay: .15s; }}
.typing-dots span:nth-child(3) {{ animation-delay: .30s; }}
@keyframes fitb-bounce {{
    0%, 80%, 100% {{ opacity: .25; transform: translateY(0); }}
    40% {{ opacity: 1; transform: translateY(-5px); }}
}}

/* ---- sidebar ---- */
[data-testid="stSidebar"] {{
    background: #1a1620;
    border-right: 1px solid rgba(218,163,96,.14);
}}
[data-testid="stSidebar"] .stButton > button {{
    width: 100%; text-align: left; justify-content: flex-start;
    background: rgba(88,68,154,.14); color: {BRAND['text']};
    border: 1px solid rgba(88,68,154,.45); border-radius: 12px;
    padding: .55rem .85rem; font-size: .88rem; font-weight: 500;
    transition: all .15s ease;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    border-color: {BRAND['gold']}; color: {BRAND['gold']};
    background: rgba(218,163,96,.08); transform: translateX(3px);
}}
.fresh-card {{
    background: rgba(218,163,96,.08); border: 1px solid rgba(218,163,96,.25);
    border-radius: 12px; padding: .65rem .8rem; font-size: .8rem;
    color: {BRAND['text']};
}}
.fresh-card b {{ color: {BRAND['gold']}; }}

/* ---- chat input ---- */
[data-testid="stChatInput"] {{
    background: {BRAND['card']};
    border: 1px solid rgba(218,163,96,.35); border-radius: 14px;
}}
[data-testid="stChatInput"] textarea {{ color: {BRAND['text']} !important; }}

/* ---- contact link button ---- */
[data-testid="stLinkButton"] a, .stLinkButton a {{
    background: linear-gradient(135deg, {BRAND['gold']}, #b8854a) !important;
    color: #1b1610 !important; font-weight: 700 !important;
    border: none !important; border-radius: 12px !important;
}}

/* ---- footer ---- */
.fitbot-footer {{
    margin-top: 2.2rem; padding-top: 1rem; text-align: center;
    border-top: 1px solid rgba(255,255,255,.07);
    color: {BRAND['muted']}; font-size: .76rem; line-height: 1.7;
}}
.fitbot-footer a {{ color: {BRAND['gold']}; text-decoration: none; }}
"""

st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Boot: background scheduler + embedding model warm-up (runs once per server)
# ---------------------------------------------------------------------------


@st.cache_resource(show_spinner=False)
def _boot() -> bool:
    start_scheduler()
    try:
        vectorstore.get_embedder()
    except Exception:
        pass  # surfaced later with a friendly message on first query
    return True


with st.spinner("A acordar o FitBot... 💪"):
    _boot()

if "messages" not in st.session_state:
    st.session_state.messages = []


def _queue_prompt(text: str) -> None:
    st.session_state.queued_prompt = text


def _clear_chat() -> None:
    st.session_state.messages = []


def _fmt_ts(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is not None:
            dt = dt.astimezone()  # UTC -> hora local
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return ts


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

QUICK_ACTIONS = [
    ("📅 Horário de aulas desta semana", "Qual é o horário de aulas desta semana?"),
    ("💳 Planos e preços", "Quais são os planos e preços do FIT IT?"),
    ("🏋️ Que modalidades têm?", "Que modalidades e aulas têm disponíveis?"),
    ("📍 Localização e horário de funcionamento",
     "Onde fica o FIT IT e qual é o horário de funcionamento?"),
    ("✍️ Como me posso inscrever?", "Como me posso inscrever no FIT IT?"),
]

with st.sidebar:
    st.markdown(
        """<div style="text-align:center; padding:.4rem 0 .8rem 0;">
        <span style="font-size:1.6rem; font-weight:800; letter-spacing:.18em;
        color:#daa360;">FIT&nbsp;IT</span><br>
        <span style="font-size:.95rem; color:#f2efe9;">Assistente virtual do FitIt 💪</span>
        </div>""",
        unsafe_allow_html=True,
    )
    st.markdown("**Perguntas rápidas**")
    for i, (label, message) in enumerate(QUICK_ACTIONS):
        st.button(label, key=f"qa_{i}", on_click=_queue_prompt, args=(message,),
                  use_container_width=True)

    st.markdown("")
    status = updater.get_status()
    sched_ts = _fmt_ts(status.get("last_schedule_update")
                       or status.get("last_schedule_crawl"))
    st.markdown(
        f"""<div class="fresh-card">📅 <b>Horário atualizado em:</b><br>
        {sched_ts or 'ainda não sincronizado'}</div>""",
        unsafe_allow_html=True,
    )
    runs = next_run_times()
    if runs.get("weekly_schedule_update"):
        st.caption(f"Próxima sincronização: {runs['weekly_schedule_update']}")

    st.markdown("")
    st.button("🗑️ Limpar conversa", key="clear_btn", on_click=_clear_chat,
              use_container_width=True)
    st.caption("Sincronização automática: horário às segundas 07:00 · "
               "site completo no dia 1 de cada mês.")

# ---------------------------------------------------------------------------
# Main chat area
# ---------------------------------------------------------------------------

st.markdown(
    """<div class="fitbot-hero">
    <div class="logo">FITBOT</div>
    <div class="tag">O teu assistente FIT IT — aulas · horários · planos</div>
    </div>""",
    unsafe_allow_html=True,
)

try:
    _counts = vectorstore.collection_counts()
    _index_ready = sum(_counts.values()) > 0
except Exception:
    _counts, _index_ready = {}, False

if not _index_ready:
    st.warning(
        "A base de conhecimento ainda está vazia. Corre `python ingest.py` "
        "no terminal para indexar o site fitit.pt e volta a abrir a app.",
        icon="⚠️",
    )


def _render_message(msg: dict) -> None:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            links = " · ".join(f"[{name}]({url})" for name, url in msg["sources"])
            st.caption(f"📎 Fontes: {links}")
        if msg.get("contact"):
            st.link_button("Falar com a equipa FitIt →", CONTACT_URL)


if not st.session_state.messages:
    with st.chat_message("assistant"):
        st.markdown(
            "Olá! Sou o **FitBot**, o assistente virtual do FIT IT 💪\n\n"
            "Pergunta-me sobre **aulas e horários**, **planos e preços**, "
            "**modalidades** ou **como te inscreveres**. Estou aqui para ajudar!"
        )

for _msg in st.session_state.messages:
    _render_message(_msg)

user_input = st.chat_input("Escreve a tua pergunta... ex: que aulas há na segunda?")
_queued = st.session_state.pop("queued_prompt", None)
if _queued and not user_input:
    user_input = _queued

if user_input:
    with st.chat_message("user"):
        st.markdown(user_input)

    history = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown(
            '<div class="typing-dots"><span></span><span></span><span></span></div>',
            unsafe_allow_html=True,
        )
        sources: list[tuple[str, str]] = []
        try:
            search_query = (
                generation.rewrite_followup(user_input, history) if history else user_input
            )
            intent, results = retrieval.retrieve(search_query)
            context = retrieval.format_context(results)
            out = generation.generate_answer(user_input, context, history)
        except Exception:
            out = {
                "answer": (
                    "Não consigo aceder à base de conhecimento neste momento. 😕 "
                    "Se o problema persistir, corre `python ingest.py` para "
                    "reconstruir o índice — ou fala diretamente com a equipa FIT IT."
                ),
                "no_info": True,
                "error": True,
            }
            results = []

        placeholder.markdown(out["answer"])

        if not out.get("error"):
            seen = set()
            for r in results:
                url = r["metadata"].get("source_url", "")
                if url and url not in seen and len(sources) < 3:
                    seen.add(url)
                    name = url.rstrip("/").rsplit("/", 1)[-1] or "fitit.pt"
                    sources.append((name, url))
            if sources:
                links = " · ".join(f"[{n}]({u})" for n, u in sources)
                st.caption(f"📎 Fontes: {links}")

        contact = bool(out.get("no_info") or out.get("error"))
        if contact:
            st.link_button("Falar com a equipa FitIt →", CONTACT_URL)

    st.session_state.messages.append({
        "role": "assistant",
        "content": out["answer"],
        "sources": sources,
        "contact": contact,
    })

# Smooth scroll to the newest message after each rerun.
components_html(
    """<script>
    const msgs = window.parent.document.querySelectorAll('[data-testid="stChatMessage"]');
    if (msgs.length) {
        msgs[msgs.length - 1].scrollIntoView({behavior: 'smooth', block: 'end'});
    }
    </script>""",
    height=0,
)

st.markdown(
    """<div class="fitbot-footer">
    Informação retirada diretamente de
    <a href="https://fitit.pt/" target="_blank">fitit.pt</a><br>
    🔄 O horário de aulas é sincronizado automaticamente todas as semanas.
    </div>""",
    unsafe_allow_html=True,
)
