"""
infrastructure/llm/client.py
The ONLY entry point for all LLM calls in DYNAFIT.
Enforces retry, token counting, cost tracking, and LangSmith tracing.
NEVER call the Anthropic SDK directly — always use llm_call().
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from core.config.settings import settings

log = structlog.get_logger()


@dataclass
class LLMResponse:
    """Structured response from a single LLM call."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_cost_usd: float
    latency_ms: float


class LLMAuthError(Exception):
    """Invalid API key — do not retry."""


class LLMRateLimitError(Exception):
    """Rate limited — retry with backoff."""


class LLMBadRequestError(Exception):
    """Bad request (prompt too long, invalid params) — do not retry."""


class LLMServerError(Exception):
    """Anthropic server error — retry."""


def _calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate USD cost for an LLM call based on current Anthropic pricing."""
    # Pricing per 1M tokens (update when Anthropic changes pricing)
    PRICING: dict[str, dict[str, float]] = {
        "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
        "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
        "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
        "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    }
    rates = PRICING.get(model, {"input": 3.00, "output": 15.00})  # Default to Sonnet rates
    return (prompt_tokens / 1_000_000 * rates["input"]) + (
        completion_tokens / 1_000_000 * rates["output"]
    )


@retry(
    stop=stop_after_attempt(settings.LLM_MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((LLMRateLimitError, LLMServerError)),
    reraise=True,
)
async def llm_call(
    messages: list[dict],
    model: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    trace_name: str | None = None,
    run_id: str | None = None,
) -> LLMResponse:
    """
    Central LLM call function. ALL LLM calls in DYNAFIT go through here.

    Features:
    - Automatic retry with exponential backoff (up to LLM_MAX_RETRIES)
    - Token counting (actual post-call)
    - Cost calculation (USD)
    - LangSmith tracing (if LANGCHAIN_API_KEY is set)
    - Structured error handling with typed exceptions

    Args:
        messages: Anthropic messages format [{"role": "...", "content": "..."}]
        model: Anthropic model name (e.g. "claude-3-5-sonnet-20241022")
        temperature: Override default temperature (default: settings.LLM_TEMPERATURE)
        max_tokens: Override max completion tokens
        trace_name: Human-readable name for LangSmith trace
        run_id: Pipeline run UUID for trace correlation

    Returns:
        LLMResponse with content, token counts, and cost.

    Raises:
        LLMAuthError: Invalid API key (not retried)
        LLMBadRequestError: Invalid parameters or prompt too long (not retried)
        LLMRateLimitError: Rate limit exceeded (auto-retried)
        LLMServerError: Anthropic server error (auto-retried)
    """
    import anthropic

    if temperature is None:
        temperature = settings.LLM_TEMPERATURE

    if max_tokens is None:
        if "haiku" in model:
            max_tokens = settings.INGESTION_MAX_TOKENS
        else:
            max_tokens = settings.CLASSIFICATION_MAX_TOKENS

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Separate system message from user messages if present
    system_message: str | None = None
    filtered_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system_message = msg["content"]
        else:
            filtered_messages.append(msg)

    start_time = time.monotonic()

    try:
        # Optional LangSmith tracing
        ls_run = None
        if settings.LANGCHAIN_API_KEY:
            try:
                import langsmith
                ls_client = langsmith.Client(api_key=settings.LANGCHAIN_API_KEY)
                # Create a run — gracefully degrade if LangSmith is down
                ls_run = ls_client.create_run(
                    name=trace_name or "llm_call",
                    run_type="llm",
                    project_name=settings.LANGCHAIN_PROJECT,
                    inputs={"messages": messages, "model": model},
                    extra={"run_id": run_id},
                )
            except Exception as ls_err:
                log.warning("langsmith_trace_init_failed", error=str(ls_err))

        create_kwargs: dict = dict(
            model=model,
            messages=filtered_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if system_message:
            create_kwargs["system"] = system_message

        response = await client.messages.create(**create_kwargs)

        latency_ms = (time.monotonic() - start_time) * 1000
        content = response.content[0].text if response.content else ""
        prompt_tokens = response.usage.input_tokens
        completion_tokens = response.usage.output_tokens
        cost = _calculate_cost(model, prompt_tokens, completion_tokens)

        log.info(
            "llm_call.success",
            model=model,
            trace_name=trace_name,
            run_id=run_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=round(cost, 4),
            latency_ms=round(latency_ms, 1),
        )

        if ls_run:
            try:
                ls_client.update_run(  # type: ignore[possibly-undefined]
                    ls_run.id,
                    outputs={"content": content},
                    end_time=None,
                    extra={"cost_usd": cost},
                )
            except Exception:
                pass  # LangSmith failure never breaks the call

        return LLMResponse(
            content=content,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_cost_usd=cost,
            latency_ms=latency_ms,
        )

    except anthropic.AuthenticationError as e:
        log.error("llm_call.auth_error", model=model, run_id=run_id, error=str(e))
        raise LLMAuthError(str(e)) from e
    except anthropic.BadRequestError as e:
        log.error("llm_call.bad_request", model=model, run_id=run_id, error=str(e))
        raise LLMBadRequestError(str(e)) from e
    except anthropic.RateLimitError as e:
        log.warning("llm_call.rate_limited", model=model, run_id=run_id, error=str(e))
        raise LLMRateLimitError(str(e)) from e
    except (anthropic.APIConnectionError, anthropic.InternalServerError) as e:
        log.warning("llm_call.server_error", model=model, run_id=run_id, error=str(e))
        raise LLMServerError(str(e)) from e
    except Exception as e:
        log.error("llm_call.unexpected_error", model=model, run_id=run_id, error=str(e), exc_info=True)
        raise


async def estimate_cost_for_batch(
    sample_messages: list[list[dict]],
    model: str,
    total_count: int,
) -> float:
    """
    Estimate total LLM cost for a batch run without making LLM calls.
    Uses tiktoken for token counting.

    Args:
        sample_messages: Sample of up to 20 message lists to estimate token counts
        model: Target model for cost calculation
        total_count: Total number of atoms to process (for extrapolation)

    Returns:
        Estimated total cost in USD.
    """
    try:
        import tiktoken

        # Use cl100k_base as proxy for Anthropic token counting (close approximation)
        enc = tiktoken.get_encoding("cl100k_base")

        total_tokens = 0
        for msgs in sample_messages[:20]:
            for msg in msgs:
                total_tokens += len(enc.encode(msg.get("content", "")))

        avg_tokens_per_call = total_tokens / max(len(sample_messages), 1)
        # Assume ~300 completion tokens per classification call
        estimated_input = avg_tokens_per_call * total_count
        estimated_output = 300 * total_count
        estimated_cost = _calculate_cost(model, int(estimated_input), int(estimated_output))

        log.info(
            "cost_preflight",
            sample_size=len(sample_messages),
            total_count=total_count,
            avg_tokens_per_call=int(avg_tokens_per_call),
            estimated_cost_usd=round(estimated_cost, 2),
        )
        return estimated_cost
    except Exception as e:
        log.warning("cost_preflight_failed", error=str(e))
        return 0.0  # Cannot estimate — proceed but warn
