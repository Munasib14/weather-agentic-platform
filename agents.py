"""
Fully agentic weather platform.

* Planner  : supervisor LLM. Runs in a loop (observe -> decide -> observe ...).
             It REPLANS after every worker result, including failures.
* Workers  : each is an autonomous tool-using agent (LLM + MCP tools). The LLM
             chooses which MCP tool to call, with which arguments, and
             self-corrects (e.g. retries geocoding with another spelling).
* Tools    : all served by the local MCP server (mcp_server.py) over stdio.
"""
import os
import sys
import json
import asyncio
import operator
from typing import Annotated, Sequence, TypedDict, List, Dict, Optional

from pydantic import BaseModel, Field
from langchain_core.messages import (
    BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage,
)
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from llm_config import get_groq_llm, get_structured_planner_llm

# ==========================================
# 1. CONFIG
# ==========================================
WORKERS = ["GeocodeWorker", "WeatherFetchWorker", "SafetyWorker"]

MAX_PLANNER_STEPS = 8        # hard budget of worker dispatches per question
MAX_WORKER_ATTEMPTS = 2      # planner-level retries per worker
MAX_TOOL_ROUNDS = 6          # LLM<->tool iterations inside one worker run
AGENT_TIMEOUT_SECONDS = 90   # whole worker run (incl. in-agent retries)
MAX_TOOL_OUTPUT_CHARS = 4000

BASE_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
MCP_SERVER_PATH = os.path.join(BASE_PROJECT_DIR, "mcp_server.py")

mcp_params = StdioServerParameters(
    command=sys.executable,
    args=[MCP_SERVER_PATH],
    env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": BASE_PROJECT_DIR},
)

WEATHER_TOOLS = {"get_forecast", "get_daily_forecast"}


# ==========================================
# 2. STATE & PLANNER SCHEMA
# ==========================================
class PlannerOutput(BaseModel):
    """One supervisor decision. The planner is called again after every worker."""
    reasoning: str = Field(
        default="",
        description="1-3 sentences: what the observations show and why you chose this next step.",
    )
    next_worker: str = Field(
        description="One of 'GeocodeWorker', 'WeatherFetchWorker', 'SafetyWorker', 'FinalResponse'."
    )
    task_instruction: str = Field(
        default="",
        description=(
            "Short plain instruction (one sentence) for the chosen worker. Include any retry hint "
            "(alternate spelling, country, different approach) and any coordinates the user typed."
        ),
    )


class AdvancedWeatherState(TypedDict, total=False):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    target_location: str
    coordinates: dict
    raw_weather_payload: str
    safety_alerts: List[str]
    risk_report: str
    observations: List[str]        # running log of worker outcomes (success AND failure)
    attempts: Dict[str, int]       # planner-level attempts per worker
    steps_taken: int
    planned_for: int               # len(messages) at start of this question
    next_node_decision: str
    worker_instruction: str
    final_output: str


planner_llm = get_structured_planner_llm(PlannerOutput)
worker_llm = get_groq_llm(model_name="openai/gpt-oss-20b", temperature=0.1)


# ==========================================
# 3. TOOL-CALLING AGENT RUNTIME (MCP)
# ==========================================
def _mcp_tool_to_openai(tool) -> dict:
    # MCP SDK v1 uses `inputSchema`, v2 uses `input_schema`
    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": schema or {"type": "object", "properties": {}},
        },
    }


def _root_cause(exc: BaseException) -> str:
    """Unwrap (nested) ExceptionGroups so logs show the real error."""
    while getattr(exc, "exceptions", None):
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}"


def _tool_text(res) -> str:
    content = getattr(res, "content", None)
    if isinstance(content, list) and content:
        first = content[0]
        text = first.text if hasattr(first, "text") else str(first)
    elif content is not None and hasattr(content, "text"):
        text = content.text
    else:
        text = str(res)
    if getattr(res, "is_error", False) or getattr(res, "isError", False):  # v2 / v1
        text = f"TOOL_ERROR: {text}"
    return text[:MAX_TOOL_OUTPUT_CHARS]


def _finish_tool(name: str, description: str, properties: dict, required: List[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


STATUS_PROP = {"type": "string", "enum": ["success", "failed"]}

GEOCODE_FINISH = _finish_tool(
    "finish_geocoding",
    "Call ONCE when you are done to report the result.",
    {
        "status": STATUS_PROP,
        "summary": {"type": "string", "description": "What you did and what happened."},
        "latitude": {"type": "number"},
        "longitude": {"type": "number"},
        "place_name": {"type": "string", "description": "Resolved place name."},
    },
    ["status", "summary"],
)
WEATHER_FINISH = _finish_tool(
    "finish_weather",
    "Call ONCE when you are done to report the result.",
    {"status": STATUS_PROP, "summary": {"type": "string"}},
    ["status", "summary"],
)
SAFETY_FINISH = _finish_tool(
    "finish_safety",
    "Call ONCE when you are done to report the safety assessment.",
    {
        "status": STATUS_PROP,
        "summary": {"type": "string"},
        "risk_level": {"type": "string", "enum": ["LOW", "MODERATE", "HIGH"]},
        "alerts": {"type": "array", "items": {"type": "string"}},
    },
    ["status", "summary"],
)


async def run_tool_agent(*, agent_name: str, system_prompt: str, task: str,
                         allowed_tools: set, finish_tool: dict) -> dict:
    """
    ReAct-style loop: the LLM picks MCP tools until it calls its finish tool.
    Returns {"finish": dict | None, "tool_outputs": [(tool, args, text), ...]}.
    """
    finish_name = finish_tool["function"]["name"]
    tool_outputs: list = []

    async with stdio_client(mcp_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = await session.list_tools()
            mcp_tools = [_mcp_tool_to_openai(t) for t in listed.tools if t.name in allowed_tools]
            llm = worker_llm.bind_tools(mcp_tools + [finish_tool])

            msgs: list = [SystemMessage(content=system_prompt), HumanMessage(content=task)]

            for round_no in range(MAX_TOOL_ROUNDS):
                ai = await llm.ainvoke(msgs)
                msgs.append(ai)
                calls = getattr(ai, "tool_calls", None) or []

                if not calls:  # model answered in prose: push it to report formally
                    msgs.append(HumanMessage(content=f"Report your result now by calling `{finish_name}`."))
                    continue

                for call in calls:
                    name = call["name"]
                    args = call.get("args") or {}
                    call_id = call.get("id") or f"call_{round_no}"

                    if name == finish_name:
                        print(f"   🏁 {agent_name} finished: {args.get('status')} - {args.get('summary')}")
                        return {"finish": args, "tool_outputs": tool_outputs}

                    if name not in allowed_tools:
                        text = f"TOOL_ERROR: tool '{name}' is not available to {agent_name}."
                    else:
                        try:
                            print(f"   🔧 {agent_name} -> MCP tool {name}({args})")
                            text = _tool_text(await session.call_tool(name, args))
                        except Exception as e:
                            text = f"TOOL_ERROR: {type(e).__name__}: {e}"
                    tool_outputs.append((name, args, text))
                    msgs.append(ToolMessage(content=text, tool_call_id=call_id, name=name))

    return {"finish": None, "tool_outputs": tool_outputs}


async def _run_agent_safely(**kwargs) -> dict:
    try:
        return await asyncio.wait_for(run_tool_agent(**kwargs), timeout=AGENT_TIMEOUT_SECONDS)
    except Exception as e:
        cause = _root_cause(e)
        print(f"   ❌ {kwargs.get('agent_name')} crashed: {cause}")
        return {"finish": None, "tool_outputs": [], "error": cause}


# ==========================================
# 4. SMALL HELPERS
# ==========================================
def _last_user_question(state) -> str:
    for m in reversed(list(state["messages"])):
        if isinstance(m, HumanMessage):
            return str(m.content)
    return ""


def _json_or_none(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


def _as_float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _valid_coords(lat, lon) -> bool:
    lat, lon = _as_float(lat), _as_float(lon)
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180


def _record(state, worker: str, status: str, summary: str) -> dict:
    """Append an observation and bump the attempt counter for this worker."""
    obs = list(state.get("observations", []))
    obs.append(f"[{worker}] {status.upper()}: {summary}")
    attempts = dict(state.get("attempts", {}))
    attempts[worker] = attempts.get(worker, 0) + 1
    return {"observations": obs, "attempts": attempts}


def _good_tool_output(text: str) -> bool:
    if text.startswith("TOOL_ERROR"):
        return False
    data = _json_or_none(text)
    return not (isinstance(data, dict) and "error" in data)


def _data_snapshot(state) -> str:
    c = state.get("coordinates") or {}
    lines = [
        f"Location: {state.get('target_location') or 'unknown'}",
        f"Coordinates: {c['lat']}, {c['lon']} ({c.get('name', '')})" if "lat" in c else "Coordinates: none",
        f"Weather data: {state['raw_weather_payload']}" if state.get("raw_weather_payload") else "Weather data: none",
        f"Safety: {state.get('risk_report', '')} | alerts: {'; '.join(state['safety_alerts'])}"
        if state.get("safety_alerts") else "Safety: none",
    ]
    return "\n".join(lines)


async def _compose_final(state, forced_reason: str = "") -> str:
    obs = "\n".join(state.get("observations", [])) or "(no worker ran)"
    prompt = (
        "Write the final reply to the user. Use ONLY the data below, never invent values. "
        "Never mention internal worker, agent or tool names. "
        "If something failed, say so honestly and tell the user what they could try "
        "(e.g. a different spelling or coordinates).\n\n"
        f"User question: {_last_user_question(state)}\n"
        f"{('Reason for stopping: ' + forced_reason) if forced_reason else ''}\n\n"
        f"Worker observations:\n{obs}\n\nCollected data:\n{_data_snapshot(state)}"
    )
    try:
        res = await worker_llm.ainvoke([HumanMessage(content=prompt)])
        text = res.content.strip()
        if text:
            return text
    except Exception as e:
        print(f"⚠️ Final-answer LLM call failed: {_root_cause(e)[:300]}")
    # last-resort answer built without an LLM
    return ("Here is what I found:\n" + _data_snapshot(state) + "\n\nNotes:\n"
            + "\n".join(state.get("observations", [])))


# ==========================================
# 5. PLANNER (SUPERVISOR, REPLANS EVERY LOOP)
# ==========================================
PLANNER_PROMPT = """You are the Planner (supervisor) of an autonomous weather multi-agent system.
You work in a loop: look at the state, decide ONE next step, then you are called again with the result.
You must REPLAN after every result, especially after failures.

WORKERS (each is an autonomous agent that chooses its own MCP tools):
- GeocodeWorker      : tool geocode_location (OpenStreetMap Nominatim). Place name -> lat/lon.
                       It retries alternate spellings by itself.
- WeatherFetchWorker : tools get_forecast (current) and get_daily_forecast (1-7 days) from Open-Meteo.
                       Needs coordinates (already resolved, or typed by the user in the question).
- SafetyWorker       : tool assess_weather_risk (rule-based drone/travel risk). Needs weather data already fetched,
                       OR conditions (wind, temperature, rain, humidity) typed by the user in the question.

{state_block}

HOW TO DECIDE:
1. Run only the workers the question actually needs. Locating a place needs only GeocodeWorker.
   Weather needs coordinates then WeatherFetchWorker. Safety/drone/travel-risk also needs SafetyWorker.
2. If the user typed the weather conditions themselves, go straight to SafetyWorker (no Geocode/Weather needed).
   If the user typed coordinates, skip GeocodeWorker and put them in task_instruction for WeatherFetchWorker.
3. If a location is required but the user gave none, choose FinalResponse and ask for it.
4. If a worker FAILED, replan: retry the same worker with a DIFFERENT task_instruction
   (alternate spelling, add country/state, other approach), switch strategy, or choose FinalResponse
   and honestly explain. Never repeat an identical instruction. Each worker may be tried at most {max_attempts} times.
5. Small talk or general questions: FinalResponse directly.
6. FinalResponse: choose it when you have enough information (or must stop). Do NOT write the reply yourself;
   a separate step writes it from the collected data.

Always fill 'reasoning' first, then 'next_worker'."""


def _reset_for_new_question(n_messages: int) -> dict:
    return {
        "planned_for": n_messages,
        "target_location": "",
        "coordinates": {},
        "raw_weather_payload": "",
        "safety_alerts": [],
        "risk_report": "",
        "observations": [],
        "attempts": {},
        "steps_taken": 0,
        "worker_instruction": "",
        "final_output": "",
    }


async def _finish(state, update: dict, answer: str) -> dict:
    return {
        **update,
        "next_node_decision": "FinalResponse",
        "final_output": answer,
        "messages": [AIMessage(content=answer)],   # keeps follow-up context for the next turn
    }


ROUTING_NUDGE = (
    "Now output ONLY your routing decision by calling the function (reasoning, next_worker, task_instruction). "
    "Do NOT write the answer, plan, table or any prose for the user. If you have enough information, "
    "set next_worker='FinalResponse'; the reply is written in a separate step."
)


async def _decide(prompt: str, msgs: list):
    """
    Call the structured planner. Retries once. A common failure is the model writing the
    user's answer as prose instead of calling the routing function (Groq 'tool_use_failed').
    """
    for attempt in (1, 2):
        try:
            return await planner_llm.ainvoke(
                [HumanMessage(content=prompt)] + msgs + [HumanMessage(content=ROUTING_NUDGE)]
            )
        except Exception as e:
            print(f"🧭 Planner LLM call failed (attempt {attempt}/2): {_root_cause(e)[:300]}")
    return None


async def planner_agent(state: AdvancedWeatherState):
    msgs = list(state["messages"])
    update: dict = {}

    if state.get("planned_for") != len(msgs):          # a new user question
        update = _reset_for_new_question(len(msgs))
    merged = {**state, **update}

    steps = merged.get("steps_taken", 0)
    attempts = merged.get("attempts", {})

    if steps >= MAX_PLANNER_STEPS:
        print("🧭 Planner: step budget reached -> finalizing")
        return await _finish(merged, update, await _compose_final(merged, "step budget reached"))

    state_block = (
        "CURRENT STATE\n"
        f"{_data_snapshot(merged)}\n"
        f"Attempts so far: {attempts or 'none'}\n"
        "OBSERVATIONS (oldest first):\n"
        + ("\n".join(f"- {o}" for o in merged.get("observations", [])) or "- none yet")
    )
    prompt = PLANNER_PROMPT.format(state_block=state_block, max_attempts=MAX_WORKER_ATTEMPTS)
    decision = await _decide(prompt, msgs)
    if decision is None:   # planner LLM failed twice: degrade gracefully, never 500
        if merged.get("observations"):
            answer = await _compose_final(merged, "the planner model was unavailable")
        else:
            answer = "Sorry, I had trouble processing that request. Please try rephrasing it."
        return await _finish(merged, update, answer)

    lookup = {w.lower(): w for w in WORKERS + ["FinalResponse"]}
    nxt = lookup.get((decision.next_worker or "").strip().lower(), "FinalResponse")
    print(f"🧭 Planner: {decision.reasoning.strip()} -> {nxt}")

    if nxt in WORKERS and attempts.get(nxt, 0) >= MAX_WORKER_ATTEMPTS:
        reason = f"{nxt} already failed {attempts[nxt]} times"
        print(f"🧭 Planner: {reason} -> finalizing")
        return await _finish(merged, update, await _compose_final(merged, reason))

    if nxt == "FinalResponse":
        return await _finish(merged, update, await _compose_final(merged))

    return {
        **update,
        "next_node_decision": nxt,
        "worker_instruction": decision.task_instruction.strip(),
        "steps_taken": steps + 1,
    }


# ==========================================
# 6. WORKER AGENTS
# ==========================================
GEOCODE_PROMPT = """You are GeocodeWorker, an autonomous agent with the MCP tool `geocode_location` (OpenStreetMap Nominatim).
Goal: find the coordinates of the place the planner asks for.
SELF-CORRECT: if `results` is empty or the match looks wrong, try again with a different query:
fix spelling, use the common English name (e.g. 'Dilli' -> 'Delhi'), add the country/state, or simplify.
You may call the tool up to 3 times. Pick the best candidate, then call `finish_geocoding` ONCE.
If nothing works, call `finish_geocoding` with status='failed' and explain what you tried. Never invent coordinates."""

WEATHER_PROMPT = """You are WeatherFetchWorker, an autonomous agent with MCP tools:
- get_forecast(latitude, longitude): CURRENT conditions
- get_daily_forecast(latitude, longitude, days): multi-day outlook
Choose the tool that fits the question (current -> get_forecast, tomorrow/weekend/next days -> get_daily_forecast;
call both if useful). Use coordinates from 'Known coordinates' or numbers typed by the user. NEVER invent coordinates.
If you have no coordinates, call `finish_weather` with status='failed' and say that coordinates are missing.
If a tool returns an error, you may retry once. Then call `finish_weather` ONCE."""

SAFETY_PROMPT = """You are SafetyWorker, an autonomous agent with the MCP tool `assess_weather_risk`.
You receive either fetched weather data (JSON) or conditions typed by the user in the question. Read the numbers (temperature_c, wind_speed_kmh, precipitation_mm, humidity_pct)
and call `assess_weather_risk` with them (for multi-day data, use the worst day or call it per day if the question needs it).
Treat 'no rain' as precipitation_mm=0; omit humidity if it is not given. If temperature or wind is missing from both
sources, finish with status='failed' and say which value is missing.
Then call `finish_safety` ONCE with risk_level, the alerts list (add context-specific alerts if justified),
and a short summary. If the weather data is unusable, finish with status='failed'."""


async def geocode_worker(state: AdvancedWeatherState):
    task = (
        f"User question: {_last_user_question(state)}\n"
        f"Planner instruction: {state.get('worker_instruction') or 'Resolve the location the user asked about.'}"
    )
    out = await _run_agent_safely(
        agent_name="GeocodeWorker", system_prompt=GEOCODE_PROMPT, task=task,
        allowed_tools={"geocode_location"}, finish_tool=GEOCODE_FINISH,
    )
    fin = out.get("finish") or {}
    lat, lon, name = fin.get("latitude"), fin.get("longitude"), fin.get("place_name") or ""
    summary = fin.get("summary") or out.get("error") or ""
    ok = fin.get("status") == "success" and _valid_coords(lat, lon)

    if not fin:  # agent never reported: salvage the top Nominatim candidate if there is one
        for tool, _args, text in reversed(out.get("tool_outputs", [])):
            data = _json_or_none(text) if tool == "geocode_location" else None
            if data and data.get("results"):
                top = data["results"][0]
                lat, lon, name = top["latitude"], top["longitude"], top.get("display_name", "")
                summary, ok = f"Used top Nominatim match: {name}", True
                break

    if ok:
        lat, lon = float(lat), float(lon)
        return {
            **_record(state, "GeocodeWorker", "success", f"{summary} (lat={lat}, lon={lon})"),
            "coordinates": {"lat": lat, "lon": lon, "name": name},
            "target_location": name,
        }
    return _record(state, "GeocodeWorker", "failed", summary or "Could not resolve the location.")


async def weather_fetch_worker(state: AdvancedWeatherState):
    c = state.get("coordinates") or {}
    known = (f"Known coordinates: lat={c['lat']}, lon={c['lon']} ({c.get('name', '')})"
             if "lat" in c else "Known coordinates: none")
    task = (
        f"User question: {_last_user_question(state)}\n{known}\n"
        f"Planner instruction: {state.get('worker_instruction') or 'Fetch the weather the user asked about.'}"
    )
    out = await _run_agent_safely(
        agent_name="WeatherFetchWorker", system_prompt=WEATHER_PROMPT, task=task,
        allowed_tools=WEATHER_TOOLS, finish_tool=WEATHER_FINISH,
    )
    fin = out.get("finish") or {}
    good = [(n, a, t) for n, a, t in out.get("tool_outputs", []) if n in WEATHER_TOOLS and _good_tool_output(t)]

    if good and fin.get("status") != "failed":
        payload = "\n".join(f"{n}({json.dumps(a)}) -> {t}" for n, a, t in good)
        return {
            **_record(state, "WeatherFetchWorker", "success", fin.get("summary") or "Fetched weather data."),
            "raw_weather_payload": payload,
        }
    reason = fin.get("summary") or out.get("error") or "No weather data could be retrieved."
    return _record(state, "WeatherFetchWorker", "failed", reason)


async def safety_worker(state: AdvancedWeatherState):
    weather = state.get("raw_weather_payload", "")
    question = _last_user_question(state)
    # Fail fast only if there is neither fetched data nor numbers typed by the user.
    if not weather and not any(ch.isdigit() for ch in question):
        return _record(state, "SafetyWorker", "failed",
                       "No weather data is available and the user gave no conditions to assess.")

    task = (
        f"User question: {_last_user_question(state)}\n"
        f"Planner instruction: {state.get('worker_instruction') or 'Assess the safety risks.'}\n\n"
        f"Fetched weather data:\n{weather or '(none fetched: read the conditions typed by the user in the question)'}"
    )
    out = await _run_agent_safely(
        agent_name="SafetyWorker", system_prompt=SAFETY_PROMPT, task=task,
        allowed_tools={"assess_weather_risk"}, finish_tool=SAFETY_FINISH,
    )
    fin = out.get("finish") or {}
    alerts = [str(a) for a in (fin.get("alerts") or []) if str(a).strip()]
    level = fin.get("risk_level") or ""

    if not alerts:  # fall back to the deterministic tool output
        for tool, _args, text in reversed(out.get("tool_outputs", [])):
            data = _json_or_none(text) if tool == "assess_weather_risk" else None
            if data and data.get("alerts"):
                alerts, level = data["alerts"], data.get("risk_level", level)
                break

    if alerts and fin.get("status") != "failed":
        summary = fin.get("summary") or "Risk assessed."
        return {
            **_record(state, "SafetyWorker", "success", f"{level or 'n/a'} - {summary}"),
            "safety_alerts": alerts,
            "risk_report": f"{level}: {summary}",
        }
    return _record(state, "SafetyWorker", "failed", fin.get("summary") or out.get("error") or "Risk assessment failed.")