from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

# Import the schema state and the 4 specialized agent node functions
from agents import (
    AdvancedWeatherState, 
    planner_agent, 
    geocode_worker, 
    weather_fetch_worker, 
    safety_worker
)

def dynamic_router(state: AdvancedWeatherState):
    """
    Acts as the main logical junction switch. It reads the 'next_node_decision' 
    string written dynamically by the Planner Agent.
    """
    decision = state.get("next_node_decision")
    
    # If the Planner determines a specific worker is missing data, route directly to it
    if decision in ["GeocodeWorker", "WeatherFetchWorker", "SafetyWorker"]:
        return decision
        
    # If the decision is 'FinalResponse' or unrecognized, exit the execution loop
    return END

# Initialize the StateGraph using our custom Advanced state dictionary schema
builder = StateGraph(AdvancedWeatherState)

# Register the 4 independent agent nodes into the graph pipeline framework
builder.add_node("Planner", planner_agent)
builder.add_node("GeocodeWorker", geocode_worker)
builder.add_node("WeatherFetchWorker", weather_fetch_worker)
builder.add_node("SafetyWorker", safety_worker)

# Define the start connection
builder.add_edge(START, "Planner")

# Set up the conditional routing edges controlled by our dynamic router function
builder.add_conditional_edges(
    "Planner",
    dynamic_router,
    {
        "GeocodeWorker": "GeocodeWorker",
        "WeatherFetchWorker": "WeatherFetchWorker",
        "SafetyWorker": "SafetyWorker",
        END: END
    }
)

# CRITICAL ROUTING LOGIC: Every worker node must always point back to the Planner.
# This prevents rigid pipelining and allows the Planner to re-evaluate the state.
builder.add_edge("GeocodeWorker", "Planner")
builder.add_edge("WeatherFetchWorker", "Planner")
builder.add_edge("SafetyWorker", "Planner")

# Initialize an in-memory checkpointer layer to maintain conversational session state
memory = MemorySaver()

# Compile the final state machine graph workflow application
weather_app = builder.compile(checkpointer=memory)
