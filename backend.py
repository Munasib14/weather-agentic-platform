# MUST BE THE ABSOLUTE FIRST LINES IN YOUR ENTRYPOINT FILE
from dotenv import load_dotenv
load_dotenv()

import traceback
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from workflow import weather_app

app = FastAPI(title="Weather Multi-Agent API Engine Hub")


class ChatRequest(BaseModel):
    message: str
    session_id: str


@app.post("/api/chat")
async def process_agent_loop(payload: ChatRequest):
    """
    Invokes the LangGraph workflow. The Planner now replans after every worker,
    so a run can contain several Planner/Worker rounds (and retries).
    """
    # recursion_limit: the Planner is capped at 8 worker dispatches (≈ 17 graph steps),
    # so 40 leaves comfortable headroom while still stopping a runaway graph.
    config = {
        "configurable": {"thread_id": payload.session_id},
        "recursion_limit": 40,
    }
    initial_input = {"messages": [HumanMessage(content=payload.message)]}

    execution_history_logs = []
    loop_counter = 0
    max_safe_loops = 30   # raised from 15: replanning + retries need more events

    try:
        async for event in weather_app.astream(initial_input, config=config, stream_mode="updates"):
            loop_counter += 1
            if loop_counter > max_safe_loops:
                print("⚠️ WARNING: Safety threshold exceeded. Loop terminated.")
                break

            for node_name, node_state in event.items():
                print(f"⚙️ Running Agent Node: {node_name}")
                execution_history_logs.append(node_name)

        final_graph_state = await weather_app.aget_state(config)
        final_output_response = final_graph_state.values.get("final_output", "")

        if not final_output_response:
            final_output_response = "The multi-agent workflow completed but did not populate a final response."

        return {"logs": execution_history_logs, "response": final_output_response}

    except Exception as e:
        error_trace = traceback.format_exc()
        print("\n=== CRITICAL GRAPH FAILURE LOG ===")
        print(error_trace)
        print("==================================\n")
        raise HTTPException(
            status_code=500,
            detail={"error_summary": f"LangGraph Runtime Failure: {str(e)}"},
        )


if __name__ == "__main__":
    uvicorn.run("backend:app", host="127.0.0.1", port=8000, reload=True)