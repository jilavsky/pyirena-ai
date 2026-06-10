"""LLM provider abstraction layer.

`pyirena_ai.llm.base.LLMProvider` is the contract every provider implements.
The concrete providers live in their own modules so the optional dependency
(`anthropic`, `openai`, ...) is only imported when the matching provider is
actually used.
"""
