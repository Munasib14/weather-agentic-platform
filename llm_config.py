import os
from langchain_groq import ChatGroq
from pydantic import BaseModel

def get_groq_llm(model_name: str = "openai/gpt-oss-20b", temperature: float = 0.1):
    """
    Constructs and returns an open-source inference connection wrapper via Groq.
    Validates api key injection prior to runtime execution.
    """
    if not os.environ.get("GROQ_API_KEY"):
        raise ValueError(
            "CRITICAL: Environment variable 'GROQ_API_KEY' is missing. "
            "Please export it in your shell window before starting the services."
        )
        
    return ChatGroq(
        model=model_name,
        temperature=temperature
    )

def get_structured_planner_llm(output_schema: BaseModel):
    """
    Returns the high-capacity Groq model wrapped with strict 
    structured output schema validation rules for structural routing decisions.
    """
    # FIX: Swapped out decommissioned model for the active, reasoning-enabled model verified in your playground
    base_llm = get_groq_llm(model_name="openai/gpt-oss-120b", temperature=0.0)
    return base_llm.with_structured_output(output_schema)
