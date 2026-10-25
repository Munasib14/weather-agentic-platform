# import asyncio
# import operator
# import httpx
# import streamlit as st
# from typing import Annotated, Sequence, TypedDict, List
# from pydantic import BaseModel, Field
# from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
# from langchain_groq import ChatGroq
# from langgraph.graph import StateGraph, START, END
# from langgraph.checkpoint.memory import MemorySaver

# # ==========================================
# # 1. GRAPH STATE DEFINITION
# # ==========================================
# class AgentTask(BaseModel):
#     worker: str = Field(description="The target worker node: 'GeocodeWorker', 'WeatherFetchWorker', or 'SafetyWorker'")
#     instruction: str = Field(description="Specific instructions for this worker")

# class PlannerOutput(BaseModel):
#     next_step: str = Field(description="'execute', 'respond', or 'replan'")
#     tasks: List[AgentTask] = Field(default=[], description="List of tasks to deploy to workers")
#     final_response: str = Field(default="", description="The final answer to the user if next_step is 'respond'")

# class AdvancedWeatherState(TypedDict):
#     messages: Annotated[Sequence[BaseMessage], operator.add]
#     target_location: str
#     target_date: str          # Format: YYYY-MM-DD
#     coordinates: dict         # {"lat": float, "lon": float, "name": str}
#     raw_weather_payload: dict
#     safety_alerts: List[str]
#     current_plan: dict        # Stores the Planner's active task matrix

# # ==========================================
# # 2. OPEN-SOURCE OPEN-METEO & GEOCODE TOOLS
# # ==========================================
# async def geocode_location(city: str) -> dict:
#     """Keyless OpenStreetMap Nominatim Geocoder"""
#     url = f"https://openstreetmap.org{city}&format=json&limit=1"
#     headers = {"User-Agent": "WeatherMultiAgentPlatform/2026.1.0"}
#     async with httpx.AsyncClient() as client:
#         try:
#             res = await client.get(url, headers=headers)
#             if res.status_code == 200 and res.json():
#                 data = res.json()[0]
#                 return {"lat": float(data["lat"]), "lon": float(data["lon"]), "name": data["display_name"]}
#         except Exception:
#             pass
#     return {"error": f"Could not find coordinates for {city}"}

# async def fetch_weather_data(lat: float, lon: float, date_str: str = None) -> dict:
#     """Keyless Open-Meteo Engine for real-time forecast or historical archives"""
#     async with httpx.AsyncClient() as client:
#         try:
#             if date_str:  # Historical Lookup Route
#                 url = f"https://open-meteo.com{lat}&longitude={lon}&start_date={date_str}&end_date={date_str}&daily=temperature_2m_max,temperature_2m_min,rain_sum,wind_speed_10m_max"
#                 res = await client.get(url)
#                 if res.status_code == 200:
#                     return {"mode": "historical", "data": res.json().get("daily", {})}
#             else:  # Current Forecast Route
#                 url = f"https://open-meteo.com{lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation"
#                 res = await client.get(url)
#                 if res.status_code == 200:
#                     return {"mode": "forecast", "data": res.json().get("current", {})}
#         except Exception as e:
#             return {"error": f"API Fetch failure: {str(e)}"}
#     return {"error": "Failed to connect to weather stream"}

# # ==========================================
# # 3. CORE AGENTS INITIALIZATION (GROQ)
# # ==========================================
# # Initialize models (Ensure your GROQ_API_KEY environment variable is set)
# planner_llm = ChatGroq(model="llama3-70b-8192", temperature=0.1).with_structured_output(PlannerOutput)
# worker_llm = ChatGroq(model="llama3-8b-8192", temperature=0.2)

# # Node 1: The Planner Agent
# async def planner_agent(state: AdvancedWeatherState):
#     history = state["messages"]
#     context = (
#         f"Active Coordinates: {state.get('coordinates')}\n"
#         f"Raw Weather Data: {state.get('raw_weather_payload')}\n"
#         f"Safety Warnings: {state.get('safety_alerts')}\n"
#     )
#     system_prompt = (
#         f"You are the Core Brain Planner of an enterprise weather multi-agent platform.\n"
#         f"Analyze the context and history, then generate your next step.\n\n"
#         f"Context Window Snapshot:\n{context}\n"
#         f"Available Workers: 'GeocodeWorker' (resolves cities to coords), "
#         f"'WeatherFetchWorker' (queries current/past data), 'SafetyWorker' (calculates risk limits).\n"
#         f"Rules: Set next_step to 'execute' to fire workers, or 'respond' when you have a complete final answers."
#     )
#     # The Planner yields a structured layout directly
#     plan = await planner_llm.ainvoke([HumanMessage(content=system_prompt)] + list(history))
#     return {"current_plan": plan.dict()}

# # Node 2: Geocoding & Stream Telemetry Worker
# async def geocode_worker(state: AdvancedWeatherState):
#     instruction = next((t["instruction"] for t in state["current_plan"]["tasks"] if t["worker"] == "GeocodeWorker"), "")
#     prompt = f"Extract only the absolute city or country name from this instruction: '{instruction}'. Respond with nothing but the city name."
#     city_res = await worker_llm.ainvoke([HumanMessage(content=prompt)])
    
#     geo_data = await geocode_location(city_res.content.strip())
#     if "error" in geo_data:
#         return {"messages": [AIMessage(content=f"Geocode Error: {geo_data['error']}")]}
#     return {
#         "coordinates": geo_data,
#         "target_location": city_res.content.strip(),
#         "messages": [AIMessage(content=f"🗺️ GeocodeWorker mapped location to: {geo_data['name']} (Lat: {geo_data['lat']}, Lon: {geo_data['lon']})")]
#     }

# # Node 3: Core Weather Data Worker (The MCP/Tool Proxy)
# async def weather_fetch_worker(state: AdvancedWeatherState):
#     coords = state.get("coordinates")
#     if not coords:
#         return {"messages": [AIMessage(content="WeatherFetchWorker failed: No coordinates found in state.")]}
    
#     # Check if a specific past date is mentioned in conversation history
#     history_str = " ".join([m.content for m in state["messages"]])
#     date_prompt = f"Analyze if a historical date (past date) is requested in this text: '{history_str}'. If yes, return it strictly as YYYY-MM-DD. If it is for a current forecast, return 'None'."
#     date_res = await worker_llm.ainvoke([HumanMessage(content=date_prompt)])
#     date_str = date_res.content.strip() if "None" not in date_res.content else None

#     weather_raw = await fetch_weather_data(coords["lat"], coords["lon"], date_str)
#     return {
#         "raw_weather_payload": weather_raw,
#         "target_date": date_str if date_str else "Current Forecast",
#         "messages": [AIMessage(content=f"🌦️ WeatherFetchWorker pulled fresh stream dataset for mode: {weather_raw.get('mode')}")]
#     }

# # Node 4: Context Impact Safety Worker
# async def safety_worker(state: AdvancedWeatherState):
#     weather_info = state.get("raw_weather_payload", {})
#     prompt = (
#         f"You are the Safety Risk Analyst Worker. Analyze this raw open-source weather stream payload: {weather_info}.\n"
#         f"Calculate explicit safety hazards, outdoor travel alerts, or severe conditions. "
#         f"List any explicit alerts separated by a semi-colon ';'. If conditions are completely safe, reply with 'All Clear'."
#     )
#     res = await worker_llm.ainvoke([HumanMessage(content=prompt)])
#     alerts = [a.strip() for a in res.content.split(";") if a.strip()]
#     return {
#         "safety_alerts": alerts,
#         "messages": [AIMessage(content=f"⚠️ SafetyWorker Assessment: {res.content}")]
#     }

# # ==========================================
# # 4. LANGGRAPH STATE MACHINE COMPILATION
# # ==========================================
# def router_edge(state: AdvancedWeatherState):
#     """Conditional Routing logic controlled dynamically by the Planner's choice"""
#     plan = state["current_plan"]
#     if plan["next_step"] == "respond":
#         return END
    
#     # Fan out to the specific worker requested by the planner
#     next_worker = plan["tasks"][0]["worker"] if plan["tasks"] else None
#     if next_worker == "GeocodeWorker": return "GeocodeWorker"
#     if next_worker == "WeatherFetchWorker": return "WeatherFetchWorker"
#     if next_worker == "SafetyWorker": return "SafetyWorker"
#     return END

# # Build Graph Nodes
# builder = StateGraph(AdvancedWeatherState)
# builder.add_node("Planner", planner_agent)
# builder.add_node("GeocodeWorker", geocode_worker)
# builder.add_node("WeatherFetchWorker", weather_fetch_worker)
# builder.add_node("SafetyWorker", safety_worker)

# # Establish Graph Logic Wiring
# builder.add_edge(START, "Planner")
# builder.add_conditional_edges(
#     "Planner",
#     router_edge,
#     {
#         "GeocodeWorker": "GeocodeWorker",
#         "WeatherFetchWorker": "WeatherFetchWorker",
#         "SafetyWorker": "SafetyWorker",
#         END: END
#     }
# )
# # Workers always loop back into the Planner for the validation pass
# builder.add_edge("GeocodeWorker", "Planner")
# builder.add_edge("WeatherFetchWorker", "Planner")
# builder.add_edge("SafetyWorker", "Planner")

# # Compile with persistent in-memory checkpointer
# memory = MemorySaver()
# weather_app = builder.compile(checkpointer=memory)

# # ==========================================
# # 5. PRESENTATION LAYER (STREAMLIT UI)
# # ==========================================
# def run_ui():
#     st.set_page_config(page_title="Weather Intel Multi-Agent", page_icon="🤖", layout="wide")
#     st.title("🤖 Weather Intelligence Multi-Agent Platform")
#     st.caption("Powered by LangGraph Core • Groq Open-Source Inference Engine • Keyless Stream Pipelines [1]")

#     if "chat_history" not in st.session_state:
#         st.session_state.chat_history = []

#     # Display Chat History Logs
#     for msg in st.session_state.chat_history:
#         with st.chat_message(msg["role"]):
#             st.markdown(msg["content"])

#     # User Input Field Capturing
