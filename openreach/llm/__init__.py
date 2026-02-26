"""OpenReach LLM integration -- multi-provider client with tool-calling."""

from openreach.llm.client import (
    LLMClient,
    LLMProvider,
    ChunkType,
    StreamChunk,
    ToolDef,
    AgentTurn,
    OllamaClient,
)
