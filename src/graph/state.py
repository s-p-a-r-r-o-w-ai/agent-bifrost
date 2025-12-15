from typing import Optional, Dict, Any, List
from langgraph.graph import MessagesState

class AgentState(MessagesState):
    # ---- User intent ----
    user_query: Optional[str]

    # ---- Index discovery ----
    all_indices: Optional[List[str]]
    selected_indices: Optional[List[str]]

    # ---- Schema / metadata ----
    mappings: Optional[Dict[str, Any]]
    field_categories: Optional[Dict[str, List[str]]]
    index_patterns: Optional[List[str]]

    # ---- ES|QL generation (STRUCTURED) ----
    esql_plan: Optional[Dict[str, Any]]     # structured model output
    esql_query: Optional[str]
    revised_esql_plan: Optional[Dict[str, Any]]
    revised_esql_query: Optional[str]

    # ---- Execution ----
    query_result: Optional[Any]
    execution_error: Optional[str]
    retry_count: int = 0

    # ---- Control flags ----
    generation_success: bool = False

    # ---- Critic / reflection (STRUCTURED) ----
    critique: Optional[Dict[str, Any]]
    improved_answer: Optional[str]