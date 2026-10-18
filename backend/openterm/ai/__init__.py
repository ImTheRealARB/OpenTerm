"""Phase 16 AI layer: an agent that answers from OpenTerm's own backend routes (tools), never from memory.

AI output is model output, not data: every answer says which tool calls grounded it and lists numbers no tool returned.
Imported lazily (api.ai_of); cold start never loads it. There are no order tools and Kite has no tool at all.
"""
