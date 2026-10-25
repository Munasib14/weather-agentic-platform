# import html
# import time
# import uuid

# import httpx
# import streamlit as st

# # ==========================================
# # CONFIG
# # ==========================================
# DEFAULT_API_URL = "http://127.0.0.1:8000"
# REQUEST_TIMEOUT = 120.0

# NODE_META = {
#     "Planner": ("🧭", "Planner"),
#     "GeocodeWorker": ("📍", "Geocode"),
#     "WeatherFetchWorker": ("🌡️", "Weather (MCP)"),
#     "SafetyWorker": ("🛡️", "Safety"),
# }

# EXAMPLES = [
#     ("📍 Locate", "Where is Pune?"),
#     ("🌡️ Weather", "What's the weather in Delhi right now?"),
#     ("🛡️ Safety", "Is it safe to fly a drone in Mumbai today?"),
#     ("🔁 Self-correct", "Weather in Dilli tomorrow"),
# ]

# st.set_page_config(page_title="Weather Multi-Agent", page_icon="🌦️", layout="centered")

# st.markdown(
#     """
#     <style>
#     .block-container {padding-top: 2rem; max-width: 820px;}
#     .hero h1 {margin-bottom: 0; font-size: 2rem;}
#     .hero p {opacity: .7; margin-top: .25rem;}
#     .chip {display: inline-block; padding: 2px 10px; margin: 2px 4px 2px 0;
#            border-radius: 999px; font-size: .78rem; font-weight: 500;
#            background: rgba(120,120,160,.15); border: 1px solid rgba(120,120,160,.3);}
#     .chip.worker {background: rgba(46,160,120,.15); border-color: rgba(46,160,120,.45);}
#     .arrow {opacity: .45; margin: 0 2px; font-size: .8rem;}
#     .meta {opacity: .6; font-size: .78rem; margin-top: .25rem;}
#     </style>
#     """,
#     unsafe_allow_html=True,
# )

# # ==========================================
# # STATE
# # ==========================================
# if "session_id" not in st.session_state:
#     st.session_state.session_id = uuid.uuid4().hex[:12]
# if "messages" not in st.session_state:
#     st.session_state.messages = []
# if "api_url" not in st.session_state:
#     st.session_state.api_url = DEFAULT_API_URL


# def new_conversation():
#     st.session_state.session_id = uuid.uuid4().hex[:12]
#     st.session_state.messages = []


# # ==========================================
# # BACKEND HELPERS
# # ==========================================
# @st.cache_data(ttl=5, show_spinner=False)
# def backend_online(url: str) -> bool:
#     try:
#         return httpx.get(f"{url.rstrip('/')}/openapi.json", timeout=2.0).status_code == 200
#     except Exception:
#         return False


# def call_backend(api_url: str, message: str, session_id: str) -> dict:
#     """Returns {'response', 'logs', 'elapsed'} or {'error', 'elapsed'}."""
#     start = time.perf_counter()
#     try:
#         r = httpx.post(
#             f"{api_url.rstrip('/')}/api/chat",
#             json={"message": message, "session_id": session_id},
#             timeout=REQUEST_TIMEOUT,
#         )
#         elapsed = time.perf_counter() - start
#         if r.status_code == 200:
#             data = r.json()
#             return {
#                 "response": data.get("response", ""),
#                 "logs": data.get("logs", []),
#                 "elapsed": elapsed,
#             }
#         try:
#             detail = r.json().get("detail", {})
#             msg = detail.get("error_summary", str(detail)) if isinstance(detail, dict) else str(detail)
#         except Exception:
#             msg = r.text[:300]
#         return {"error": f"Backend error ({r.status_code}): {msg}", "elapsed": elapsed}
#     except httpx.ConnectError:
#         return {"error": f"Can't reach the backend at {api_url}. Is `python backend.py` running?",
#                 "elapsed": time.perf_counter() - start}
#     except httpx.TimeoutException:
#         return {"error": "The request timed out. The agents may still be working; try again.",
#                 "elapsed": time.perf_counter() - start}
#     except Exception as e:
#         return {"error": f"Unexpected error: {e}", "elapsed": time.perf_counter() - start}


# # ==========================================
# # RENDER HELPERS
# # ==========================================
# def trace_html(logs: list) -> str:
#     parts = []
#     for i, node in enumerate(logs):
#         icon, label = NODE_META.get(node, ("⚙️", html.escape(str(node))))
#         cls = "chip" if node == "Planner" else "chip worker"
#         parts.append(f'<span class="{cls}">{icon} {label}</span>')
#         if i < len(logs) - 1:
#             parts.append('<span class="arrow">→</span>')
#     return "".join(parts)


# def render_assistant_extras(msg: dict):
#     logs = msg.get("logs") or []
#     workers = [n for n in logs if n != "Planner"]
#     if logs:
#         used = ", ".join(dict.fromkeys(NODE_META.get(n, ("", n))[1] for n in workers)) or "none (answered directly)"
#         with st.expander(f"Agent trace · workers used: {used}"):
#             st.markdown(trace_html(logs), unsafe_allow_html=True)
#     if msg.get("elapsed") is not None:
#         st.markdown(f'<div class="meta">⏱ {msg["elapsed"]:.1f}s</div>', unsafe_allow_html=True)


# def render_message(msg: dict):
#     with st.chat_message(msg["role"], avatar="🧑‍💻" if msg["role"] == "user" else "🌦️"):
#         if msg.get("is_error"):
#             st.error(msg["content"])
#         else:
#             st.markdown(msg["content"])
#         if msg["role"] == "assistant":
#             render_assistant_extras(msg)


# # ==========================================
# # SIDEBAR
# # ==========================================
# with st.sidebar:
#     st.header("⚙️ Settings")
#     st.session_state.api_url = st.text_input("Backend URL", value=st.session_state.api_url)

#     if backend_online(st.session_state.api_url):
#         st.success("Backend online", icon="🟢")
#     else:
#         st.error("Backend offline", icon="🔴")
#         if st.button("Re-check", use_container_width=True):
#             backend_online.clear()
#             st.rerun()

#     st.divider()
#     st.caption("Conversation")
#     st.code(st.session_state.session_id, language=None)
#     st.button("🗑️ New conversation", on_click=new_conversation, use_container_width=True)

#     st.divider()
#     st.caption("How it works")
#     st.markdown(
#         "The **Planner** replans after every step and picks only the agents your question needs. "
#         "Each agent chooses its own **MCP tools** and retries when something fails."
#     )

# # ==========================================
# # MAIN
# # ==========================================
# st.markdown(
#     '<div class="hero"><h1>🌦️ Weather Multi-Agent</h1>'
#     "<p>Ask about locations, live weather, or flight and travel safety.</p></div>",
#     unsafe_allow_html=True,
# )

# if not st.session_state.messages:
#     st.markdown("**Try one of these:**")
#     cols = st.columns(2)
#     for i, (label, prompt_text) in enumerate(EXAMPLES):
#         if cols[i % 2].button(f"{label}: {prompt_text}", key=f"ex_{i}", use_container_width=True):
#             st.session_state.pending = prompt_text
#             st.rerun()

# for m in st.session_state.messages:
#     render_message(m)

# typed = st.chat_input("Ask about weather, locations, or drone safety…")
# prompt = st.session_state.pop("pending", None) or typed

# if prompt:
#     user_msg = {"role": "user", "content": prompt}
#     st.session_state.messages.append(user_msg)
#     render_message(user_msg)

#     with st.chat_message("assistant", avatar="🌦️"):
#         with st.spinner("Agents are working…"):
#             result = call_backend(st.session_state.api_url, prompt, st.session_state.session_id)

#     if "error" in result:
#         reply = {"role": "assistant", "content": result["error"], "is_error": True,
#                  "elapsed": result["elapsed"]}
#     else:
#         reply = {"role": "assistant", "content": result["response"] or "_(empty response)_",
#                  "logs": result["logs"], "elapsed": result["elapsed"]}

#     st.session_state.messages.append(reply)
#     st.rerun()



import html
import time
import uuid
from collections import Counter

import httpx
import streamlit as st

# ==========================================
# CONFIG
# ==========================================
DEFAULT_API_URL = "http://127.0.0.1:8000"
REQUEST_TIMEOUT = 120.0

NODE_META = {
    "Planner": ("🧭", "Planner", "Plans, replans and writes the final answer"),
    "GeocodeWorker": ("📍", "Geocode", "Resolved the place via Nominatim (MCP)"),
    "WeatherFetchWorker": ("🌡️", "Weather", "Fetched live data via Open-Meteo (MCP)"),
    "SafetyWorker": ("🛡️", "Safety", "Assessed risk with the rule engine (MCP)"),
}
WORKER_KEYS = ["GeocodeWorker", "WeatherFetchWorker", "SafetyWorker"]

EXAMPLES = [
    ("📍", "Locate", "Where is Pune?"),
    ("🌡️", "Live temperature", "What's the temperature in New Delhi?"),
    ("🛡️", "Drone safety", "Is it safe to fly a drone in Mumbai today?"),
    ("🔁", "Self-correction", "Weather in Dilli tomorrow"),
    ("⚡", "Typed conditions", "Wind is 45 km/h, temperature 31°C, no rain, humidity 48%. Is it safe to fly a drone?"),
    ("🗺️", "Trip planning", "Plan a 3 day trip to Jaipur with weather in mind"),
]

st.set_page_config(
    page_title="SkyMind · Weather Multi-Agent AI",
    page_icon="🌦️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ==========================================
# STYLE
# ==========================================
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;700&display=swap');

:root{
  --glass: rgba(255,255,255,.055);
  --glass-b: rgba(255,255,255,.12);
  --txt: #e8ecff;
  --mut: #9aa6d1;
  --a1: #7c5cff;
  --a2: #22d3ee;
  --a3: #f472b6;
  --ok: #34d399;
  --bad: #fb7185;
}

html, body, .stApp, [class*="css"]{ font-family: 'Inter', system-ui, sans-serif; }
.stApp{ background:#070b1a; color: var(--txt); }

/* hide Streamlit chrome for a clean, full-screen demo look */
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"]{ display:none !important; }
header[data-testid="stHeader"]{ background: transparent; }

.block-container{ max-width: 1600px; padding: 1.1rem 2.4rem 7rem; position: relative; z-index: 1; }

/* ---------- animated aurora background ---------- */
.aurora{ position: fixed; inset: 0; z-index: 0; overflow: hidden; pointer-events: none; }
.aurora span{ position:absolute; border-radius:50%; filter: blur(110px); opacity:.55; animation: drift 20s ease-in-out infinite alternate; }
.aurora span:nth-child(1){ width:620px; height:620px; background:#5b3df5; left:-140px; top:-160px; }
.aurora span:nth-child(2){ width:560px; height:560px; background:#0891b2; right:-120px; top:5%; animation-delay:-6s; }
.aurora span:nth-child(3){ width:520px; height:520px; background:#be185d; left:35%; bottom:-260px; animation-delay:-12s; opacity:.4; }
.aurora::after{ content:""; position:absolute; inset:0;
  background-image: radial-gradient(rgba(255,255,255,.09) 1px, transparent 1px); background-size: 30px 30px;
  mask-image: linear-gradient(to bottom, rgba(0,0,0,.7), transparent 75%); }
@keyframes drift{ from{ transform: translate(0,0) scale(1);} to{ transform: translate(70px,50px) scale(1.15);} }

/* ---------- hero ---------- */
.hero{ display:flex; align-items:center; justify-content:space-between; gap:24px; padding: 22px 28px; margin-bottom: 16px;
  background: linear-gradient(135deg, rgba(124,92,255,.18), rgba(34,211,238,.10)); border:1px solid var(--glass-b);
  border-radius: 24px; backdrop-filter: blur(16px); box-shadow: 0 20px 60px rgba(0,0,0,.35); animation: rise .6s ease both; }
.hero-left{ display:flex; align-items:center; gap:18px; }
.logo{ width:64px; height:64px; display:grid; place-items:center; font-size:34px; border-radius:20px;
  background: linear-gradient(135deg, var(--a1), var(--a2)); box-shadow: 0 0 40px rgba(124,92,255,.6); animation: float 4s ease-in-out infinite; }
.hero h1{ margin:0; font-family:'Space Grotesk',sans-serif; font-weight:700; font-size: 2.35rem; line-height:1.1; letter-spacing:-.5px;
  background: linear-gradient(90deg,#fff,#a5b4fc,#67e8f9,#f9a8d4,#fff); background-size:300% 100%;
  -webkit-background-clip:text; background-clip:text; color:transparent; animation: shimmer 8s linear infinite; }
.hero p{ margin:.3rem 0 0; color: var(--mut); font-size:.98rem; }
.tags{ display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end; max-width: 520px; }
.tag{ font-size:.74rem; font-weight:600; padding:5px 11px; border-radius:999px; background: var(--glass); border:1px solid var(--glass-b); color:#c7d2fe; }
.pill{ display:inline-flex; align-items:center; gap:8px; font-size:.8rem; font-weight:600; padding:6px 13px; border-radius:999px; border:1px solid var(--glass-b); background: var(--glass); margin-bottom:10px; }
.dot{ width:9px; height:9px; border-radius:50%; background: var(--ok); box-shadow:0 0 0 0 rgba(52,211,153,.7); animation: ping 1.8s infinite; }
.dot.off{ background: var(--bad); animation:none; }
@keyframes ping{ 70%{ box-shadow:0 0 0 10px rgba(52,211,153,0);} 100%{ box-shadow:0 0 0 0 rgba(52,211,153,0);} }
@keyframes shimmer{ to{ background-position: 300% 0; } }
@keyframes float{ 50%{ transform: translateY(-6px) rotate(-3deg);} }
@keyframes rise{ from{ opacity:0; transform: translateY(14px);} to{ opacity:1; transform:none;} }

/* ---------- KPI tiles ---------- */
.kpis{ display:grid; grid-template-columns: repeat(4, 1fr); gap:14px; margin-bottom: 18px; }
.kpi{ padding:16px 20px; border-radius:20px; background: var(--glass); border:1px solid var(--glass-b); backdrop-filter: blur(14px); animation: rise .6s ease both; }
.kpi .v{ font-family:'Space Grotesk',sans-serif; font-size:2rem; font-weight:700; line-height:1.1;
  background: linear-gradient(90deg,#fff,#a5b4fc); -webkit-background-clip:text; background-clip:text; color:transparent; }
.kpi .l{ color: var(--mut); font-size:.78rem; font-weight:600; text-transform:uppercase; letter-spacing:.9px; margin-top:4px; }

/* ---------- panels ---------- */
.panel{ padding:18px 20px; border-radius:22px; background: var(--glass); border:1px solid var(--glass-b); backdrop-filter: blur(14px); margin-bottom:14px; animation: rise .6s ease both; }
.panel h3{ margin:0 0 6px; font-size:.82rem; font-weight:700; text-transform:uppercase; letter-spacing:1.1px; color:#a5b4fc; }
.panel .sub{ color: var(--mut); font-size:.8rem; margin-bottom:8px; }

/* ---------- agent graph ---------- */
.agraph{ width:100%; height:auto; overflow:visible; }
.agraph .edge{ stroke:#2a3358; stroke-width:2; fill:none; }
.agraph .edge.active{ stroke:url(#gl); stroke-width:3; stroke-dasharray:6 8; animation: flow 1s linear infinite; }
@keyframes flow{ to{ stroke-dashoffset:-28; } }
.agraph .n-idle{ fill:#121a38; stroke:#2c3763; stroke-width:2; }
.agraph .n-on{ fill:url(#ga); stroke:#c4b5fd; stroke-width:2; filter:url(#glow); }
.agraph .n-plan{ fill:url(#gp); stroke:#f9a8d4; stroke-width:2.5; filter:url(#glow); }
.agraph .pulse{ animation: pulse 1.6s ease-in-out infinite; transform-box:fill-box; transform-origin:center; }
@keyframes pulse{ 50%{ transform:scale(1.09);} }
.agraph text.lbl{ fill:#c7d2fe; font-size:13px; font-weight:600; text-anchor:middle; }
.agraph text.dim{ fill:#5d6a9a; }
.agraph .badge{ fill:#34d399; } .agraph text.bt{ fill:#052e1f; font-size:12px; font-weight:800; text-anchor:middle; dominant-baseline:central; }

/* ---------- timeline ---------- */
.tl{ list-style:none; margin:6px 0 0; padding:0; position:relative; }
.tl li{ position:relative; padding:0 0 14px 44px; font-size:.86rem; color:#cbd5ff; animation: rise .4s ease both; }
.tl li::before{ content:""; position:absolute; left:15px; top:30px; bottom:0; width:2px; background: linear-gradient(var(--a1), transparent); }
.tl li:last-child::before{ display:none; }
.tl .ic{ position:absolute; left:0; top:0; width:32px; height:32px; display:grid; place-items:center; border-radius:50%;
  background: linear-gradient(135deg, var(--a1), var(--a2)); font-size:16px; box-shadow:0 0 16px rgba(124,92,255,.5); }
.tl b{ color:#fff; } .tl small{ display:block; color:var(--mut); font-size:.76rem; }

/* ---------- chips ---------- */
.chips{ margin-top:10px; display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
.chip{ font-size:.74rem; font-weight:600; padding:4px 11px; border-radius:999px; border:1px solid rgba(52,211,153,.5); background:rgba(52,211,153,.12); color:#6ee7b7; }
.chip.p{ border-color: rgba(124,92,255,.5); background: rgba(124,92,255,.14); color:#c4b5fd; }
.chip.t{ border-color: var(--glass-b); background: var(--glass); color: var(--mut); }

/* ---------- chat ---------- */
[data-testid="stChatMessage"]{ background: var(--glass); border:1px solid var(--glass-b); border-radius:20px; padding:16px 20px;
  backdrop-filter: blur(14px); margin-bottom:12px; animation: rise .35s ease both; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]){ background: linear-gradient(135deg, rgba(124,92,255,.28), rgba(34,211,238,.14)); border-color: rgba(124,92,255,.45); }
[data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li{ font-size:1.02rem; line-height:1.65; }
[data-testid="stChatMessage"] table{ border-collapse:collapse; width:100%; }
[data-testid="stChatMessage"] th, [data-testid="stChatMessage"] td{ border:1px solid var(--glass-b); padding:6px 10px; }
[data-testid="stChatMessage"] th{ background: rgba(124,92,255,.18); }

[data-testid="stChatInput"]{ border-radius:20px !important; border:1px solid rgba(124,92,255,.5) !important; background: rgba(13,19,44,.92) !important;
  box-shadow: 0 0 0 1px rgba(124,92,255,.2), 0 14px 50px rgba(0,0,0,.5), 0 0 40px rgba(124,92,255,.18); }
[data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"]{ background: transparent !important; }

/* ---------- buttons (example cards) ---------- */
div.stButton > button{ width:100%; min-height:86px; text-align:left; white-space:normal; border-radius:18px; padding:16px 18px; color: var(--txt);
  background: var(--glass); border:1px solid var(--glass-b); backdrop-filter: blur(12px); transition: all .22s ease; font-size:.95rem; line-height:1.4; }
div.stButton > button:hover{ transform: translateY(-4px); border-color: var(--a1); background: rgba(124,92,255,.16); box-shadow: 0 12px 34px rgba(124,92,255,.35); color:#fff; }
div.stButton > button:active{ transform: translateY(-1px); }

/* ---------- welcome ---------- */
.welcome{ padding: 26px 28px; border-radius:24px; margin-bottom:16px; background: linear-gradient(135deg, rgba(34,211,238,.08), rgba(124,92,255,.14)); border:1px solid var(--glass-b); animation: rise .6s ease both; }
.welcome h2{ margin:0 0 4px; font-family:'Space Grotesk',sans-serif; font-size:1.55rem; }
.welcome p{ margin:0; color: var(--mut); }

/* ---------- typing ---------- */
.typing{ display:flex; align-items:center; gap:12px; color:#c4b5fd; font-weight:600; }
.typing i{ width:9px; height:9px; border-radius:50%; background: linear-gradient(135deg,var(--a1),var(--a2)); display:inline-block; animation: bounce 1.2s infinite; }
.typing i:nth-child(2){ animation-delay:.15s; } .typing i:nth-child(3){ animation-delay:.3s; }
@keyframes bounce{ 0%,80%,100%{ transform:scale(.6); opacity:.5;} 40%{ transform:scale(1.15); opacity:1;} }

section[data-testid="stSidebar"]{ background: rgba(9,14,34,.92); border-right:1px solid var(--glass-b); }
@media (max-width: 900px){ .kpis{ grid-template-columns: repeat(2,1fr);} .hero{ flex-direction:column; align-items:flex-start; } .tags{ justify-content:flex-start; } }
</style>
<div class="aurora"><span></span><span></span><span></span></div>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ==========================================
# STATE
# ==========================================
ss = st.session_state
ss.setdefault("session_id", uuid.uuid4().hex[:12])
ss.setdefault("messages", [])
ss.setdefault("api_url", DEFAULT_API_URL)
ss.setdefault("n_questions", 0)
ss.setdefault("total_time", 0.0)
ss.setdefault("last_logs", [])


def new_conversation():
    ss.session_id = uuid.uuid4().hex[:12]
    ss.messages = []
    ss.n_questions = 0
    ss.total_time = 0.0
    ss.last_logs = []


# ==========================================
# BACKEND
# ==========================================
@st.cache_data(ttl=5, show_spinner=False)
def backend_online(url: str) -> bool:
    try:
        return httpx.get(f"{url.rstrip('/')}/openapi.json", timeout=2.0).status_code == 200
    except Exception:
        return False


def call_backend(api_url: str, message: str, session_id: str) -> dict:
    start = time.perf_counter()
    try:
        r = httpx.post(
            f"{api_url.rstrip('/')}/api/chat",
            json={"message": message, "session_id": session_id},
            timeout=REQUEST_TIMEOUT,
        )
        elapsed = time.perf_counter() - start
        if r.status_code == 200:
            data = r.json()
            return {"response": data.get("response", ""), "logs": data.get("logs", []), "elapsed": elapsed}
        try:
            detail = r.json().get("detail", {})
            msg = detail.get("error_summary", str(detail)) if isinstance(detail, dict) else str(detail)
        except Exception:
            msg = r.text[:300]
        return {"error": f"Backend error ({r.status_code}): {msg}", "elapsed": elapsed}
    except httpx.ConnectError:
        return {"error": f"Can't reach the backend at {api_url}. Is `python backend.py` running?",
                "elapsed": time.perf_counter() - start}
    except httpx.TimeoutException:
        return {"error": "The request timed out. The agents may still be working; try again.",
                "elapsed": time.perf_counter() - start}
    except Exception as e:
        return {"error": f"Unexpected error: {e}", "elapsed": time.perf_counter() - start}


# ==========================================
# HTML BUILDERS
# ==========================================
def graph_html(logs: list, running: bool = False) -> str:
    counts = Counter(logs)
    pos = {
        "Planner": (200, 72, 42),
        "GeocodeWorker": (62, 262, 36),
        "WeatherFetchWorker": (200, 262, 36),
        "SafetyWorker": (338, 262, 36),
    }
    out = [
        '<svg class="agraph" viewBox="0 0 400 340" xmlns="http://www.w3.org/2000/svg">',
        '<defs>'
        '<linearGradient id="ga" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7c5cff"/><stop offset="1" stop-color="#22d3ee"/></linearGradient>'
        '<linearGradient id="gp" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f472b6"/><stop offset="1" stop-color="#7c5cff"/></linearGradient>'
        '<linearGradient id="gl" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#c4b5fd"/><stop offset="1" stop-color="#67e8f9"/></linearGradient>'
        '<filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="5" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>',
    ]
    px, py, _ = pos["Planner"]
    for key in WORKER_KEYS:
        x, y, r = pos[key]
        active = counts.get(key, 0) > 0 or running
        out.append(f'<path class="edge{" active" if active else ""}" d="M{px} {py + 42} C {px} {py + 110}, {x} {y - 110}, {x} {y - r}"/>')

    for key, (x, y, r) in pos.items():
        icon, label, _d = NODE_META[key]
        used = counts.get(key, 0) > 0
        if key == "Planner":
            cls = "n-plan pulse" if (used or running) else "n-idle"
        else:
            cls = "n-on pulse" if used else "n-idle"
        out.append(f'<circle class="{cls}" cx="{x}" cy="{y}" r="{r}"/>')
        out.append(f'<text x="{x}" y="{y}" font-size="{30 if key == "Planner" else 26}" text-anchor="middle" dominant-baseline="central">{icon}</text>')
        dim = "" if (used or key == "Planner" or running) else " dim"
        out.append(f'<text class="lbl{dim}" x="{x}" y="{y + r + 22}">{label}</text>')
        if used and key != "Planner":
            out.append(f'<circle class="badge" cx="{x + r - 6}" cy="{y - r + 6}" r="11"/><text class="bt" x="{x + r - 6}" y="{y - r + 6}">{counts[key]}</text>')
        if key == "Planner" and used:
            out.append(f'<circle class="badge" cx="{x + r - 8}" cy="{y - r + 8}" r="12"/><text class="bt" x="{x + r - 8}" y="{y - r + 8}">{counts[key]}</text>')
    out.append("</svg>")
    return "".join(out)


def timeline_html(logs: list) -> str:
    if not logs:
        return '<div class="sub">Ask a question and watch the agents collaborate here.</div>'
    items = []
    for i, node in enumerate(logs):
        icon, label, desc = NODE_META.get(node, ("⚙️", html.escape(str(node)), ""))
        if node == "Planner":
            desc = "Wrote the final answer" if i == len(logs) - 1 else ("Planned the first step" if i == 0 else "Replanned from the result")
        items.append(f'<li style="animation-delay:{i * 0.06:.2f}s"><span class="ic">{icon}</span><b>{label}</b><small>{desc}</small></li>')
    return f'<ol class="tl">{"".join(items)}</ol>'


def kpi_html() -> str:
    avg = (ss.total_time / ss.n_questions) if ss.n_questions else 0.0
    workers_used = len({n for n in ss.last_logs if n != "Planner"})
    loops = ss.last_logs.count("Planner")
    tiles = [
        (str(ss.n_questions), "Questions asked"),
        (f"{avg:.1f}s" if ss.n_questions else "–", "Avg response time"),
        (f"{workers_used}/3" if ss.last_logs else "–", "Agents used (last run)"),
        (str(loops) if ss.last_logs else "–", "Planner loops (last run)"),
    ]
    return '<div class="kpis">' + "".join(f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div></div>' for v, l in tiles) + "</div>"


def chips_html(msg: dict) -> str:
    logs = msg.get("logs") or []
    chips = []
    for n in dict.fromkeys(x for x in logs if x != "Planner"):
        icon, label, _ = NODE_META.get(n, ("⚙️", html.escape(str(n)), ""))
        chips.append(f'<span class="chip">{icon} {label}</span>')
    if not chips and logs:
        chips.append('<span class="chip p">🧭 Answered directly</span>')
    if logs:
        chips.append(f'<span class="chip p">🔁 {logs.count("Planner")} planner loops</span>')
    if msg.get("elapsed") is not None:
        chips.append(f'<span class="chip t">⏱ {msg["elapsed"]:.1f}s</span>')
    return f'<div class="chips">{"".join(chips)}</div>' if chips else ""


def render_message(msg: dict):
    with st.chat_message(msg["role"], avatar="🧑‍💻" if msg["role"] == "user" else "🌦️"):
        if msg.get("is_error"):
            st.error(msg["content"])
        else:
            st.markdown(msg["content"])
        if msg["role"] == "assistant":
            st.markdown(chips_html(msg), unsafe_allow_html=True)


# ==========================================
# SIDEBAR
# ==========================================
with st.sidebar:
    st.markdown("### ⚙️ Settings")
    ss.api_url = st.text_input("Backend URL", value=ss.api_url)
    st.caption("Conversation ID")
    st.code(ss.session_id, language=None)
    st.button("✨ New conversation", on_click=new_conversation, key="sb_new")
    st.markdown("---")
    st.markdown("**MCP tools**")
    st.markdown("- `geocode_location` · Nominatim\n- `get_forecast` · Open-Meteo\n- `get_daily_forecast` · Open-Meteo\n- `assess_weather_risk` · rule engine")

online = backend_online(ss.api_url)

# ==========================================
# HERO + KPIs
# ==========================================
pill = ('<span class="pill"><span class="dot"></span>Backend online</span>' if online
        else '<span class="pill"><span class="dot off"></span>Backend offline</span>')
st.markdown(
    f"""
    <div class="hero">
      <div class="hero-left">
        <div class="logo">🌦️</div>
        <div>
          {pill}
          <h1>SkyMind · Weather Multi-Agent AI</h1>
          <p>A planner that replans, agents that choose their own tools, and self-correction when things go wrong.</p>
        </div>
      </div>
      <div class="tags">
        <span class="tag">LangGraph</span><span class="tag">MCP</span><span class="tag">FastAPI</span>
        <span class="tag">Groq LLMs</span><span class="tag">Open-Meteo</span><span class="tag">Nominatim</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown(kpi_html(), unsafe_allow_html=True)

# ==========================================
# MAIN LAYOUT: chat (left) + live agent graph (right)
# ==========================================
left, right = st.columns([1.75, 1], gap="large")

with right:
    graph_slot = st.empty()
    timeline_slot = st.empty()

    def paint_right(logs, running=False):
        graph_slot.markdown(
            '<div class="panel"><h3>Live agent graph</h3>'
            f'<div class="sub">{"Agents are collaborating…" if running else "Highlighted agents ran for the last question."}</div>'
            f"{graph_html(logs, running)}</div>",
            unsafe_allow_html=True,
        )
        timeline_slot.markdown(
            f'<div class="panel"><h3>Execution timeline</h3>{timeline_html([] if running else logs)}</div>',
            unsafe_allow_html=True,
        )

    paint_right(ss.last_logs)
    st.button("🗑️ Start a new conversation", on_click=new_conversation, key="new_chat")

with left:
    if not ss.messages:
        st.markdown(
            '<div class="welcome"><h2>👋 Ask me anything about weather</h2>'
            "<p>Try an example. The Planner decides which agents to call, and you can watch them light up on the right.</p></div>",
            unsafe_allow_html=True,
        )
        cols = st.columns(2)
        for i, (icon, title, prompt_text) in enumerate(EXAMPLES):
            if cols[i % 2].button(f"{icon}  {title}\n\n{prompt_text}", key=f"ex_{i}"):
                ss.pending = prompt_text
                st.rerun()
    for m in ss.messages:
        render_message(m)

typed = st.chat_input("Ask about weather, locations, drone safety, trip plans…")
prompt = ss.pop("pending", None) or typed

if prompt:
    ss.messages.append({"role": "user", "content": prompt})
    with left:
        render_message(ss.messages[-1])
        with st.chat_message("assistant", avatar="🌦️"):
            st.markdown('<div class="typing"><i></i><i></i><i></i> Agents are collaborating…</div>', unsafe_allow_html=True)
            paint_right([], running=True)
            result = call_backend(ss.api_url, prompt, ss.session_id)

    if "error" in result:
        ss.messages.append({"role": "assistant", "content": result["error"], "is_error": True, "elapsed": result["elapsed"]})
    else:
        ss.messages.append({"role": "assistant", "content": result["response"] or "_(empty response)_",
                            "logs": result["logs"], "elapsed": result["elapsed"]})
        ss.last_logs = result["logs"]
        ss.n_questions += 1
        ss.total_time += result["elapsed"]
    st.rerun()