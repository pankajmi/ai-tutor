# agents

LangGraph agents. Implementation begins at Build Layer 7 (Tutor Agent) and
Layer 8 (Orchestrator).

Expected layout (not yet created):
```
agents/
  orchestrator.py        # LangGraph StateGraph, SessionState, routing
  tutor_agent.py          # Persona "Nova", Socratic dialogue -> TutorResponse
  whiteboard_agent.py      # DrawCommand generation
  curriculum_agent.py       # CBSE chapter map, prerequisite gaps
  problem_generator_agent.py
  mistake_pattern_agent.py
  memory_agent.py            # Reads/writes Postgres + Redis state
  parent_reporting_agent.py
  models.py                   # Shared Pydantic v2 contracts (TutorResponse, DrawCommand, etc.)
```
