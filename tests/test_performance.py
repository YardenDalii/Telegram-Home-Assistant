"""Performance tests — measure Ollama inference latency.

All tests are skipped automatically when Ollama is not running.
Results are printed so they appear in `pytest -s` output.

Thresholds are deliberately generous to accommodate both development
machines and a Raspberry Pi 5 under load.
"""

import time

import pytest

# Maximum acceptable response time per Ollama call (seconds).
# Pi 5 with qwen2.5:7b typically responds in 20-60s; 120s is a safe ceiling.
_LIMIT = 120.0


def _make_client():
    import ollama
    from config import Config
    return ollama.Client(host=Config.OLLAMA_HOST)


def _simple_messages():
    return [
        {"role": "system", "content": "ענה בעברית. הגב במשפט קצר בלבד."},
        {"role": "user", "content": "שלום"},
    ]


# ---------------------------------------------------------------------------
# Helpers (not tests)
# ---------------------------------------------------------------------------

def _timed_chat(client, model: str, messages: list, tools: list | None = None) -> tuple[float, str]:
    """Run a chat call and return (elapsed_seconds, response_text)."""
    kwargs = {"model": model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
    start = time.perf_counter()
    resp = client.chat(**kwargs)
    elapsed = time.perf_counter() - start
    return elapsed, (resp.message.content or "")


# ---------------------------------------------------------------------------
# Tests — all skipped when Ollama is offline
# ---------------------------------------------------------------------------

class TestOllamaPerformance:
    """Latency benchmarks for Ollama inference."""

    def test_simple_greeting_response_time(self, ollama_up):
        """A greeting with no tools should reply within the time limit."""
        if not ollama_up:
            pytest.skip("Ollama not running")

        from config import Config
        client = _make_client()
        elapsed, content = _timed_chat(client, Config.OLLAMA_MODEL, _simple_messages())

        print(f"\n[perf] greeting response: {elapsed:.2f}s  content: {content[:60]!r}")
        assert content, "Ollama returned empty response"
        assert elapsed < _LIMIT, (
            f"Response took {elapsed:.1f}s — exceeds limit of {_LIMIT}s"
        )

    def test_shopping_tool_call_response_time(self, ollama_up):
        """A shopping request with tool schemas injected should respond in time."""
        if not ollama_up:
            pytest.skip("Ollama not running")

        from ai.assistant import _SHOPPING_TOOLS
        from config import Config
        client = _make_client()
        messages = [
            {"role": "system", "content": "ענה בעברית. השתמש בכלים בלבד."},
            {"role": "user", "content": "תוסיף חלב לרשימת הקניות"},
        ]
        elapsed, _ = _timed_chat(client, Config.OLLAMA_MODEL, messages, tools=_SHOPPING_TOOLS)

        print(f"\n[perf] shopping tool call: {elapsed:.2f}s")
        assert elapsed < _LIMIT, (
            f"Tool-call response took {elapsed:.1f}s — exceeds limit of {_LIMIT}s"
        )

    def test_reminder_tool_call_response_time(self, ollama_up):
        """A reminder request with tool schemas injected should respond in time."""
        if not ollama_up:
            pytest.skip("Ollama not running")

        from ai.assistant import _REMINDER_TOOLS
        from config import Config
        client = _make_client()
        messages = [
            {"role": "system", "content": "ענה בעברית. השתמש בכלים."},
            {"role": "user", "content": "תזכיר לי עוד 30 דקות לשתות מים"},
        ]
        elapsed, _ = _timed_chat(client, Config.OLLAMA_MODEL, messages, tools=_REMINDER_TOOLS)

        print(f"\n[perf] reminder tool call: {elapsed:.2f}s")
        assert elapsed < _LIMIT, (
            f"Reminder tool-call response took {elapsed:.1f}s — exceeds limit of {_LIMIT}s"
        )

    def test_average_response_time_over_three_calls(self, ollama_up):
        """Average of 3 consecutive greeting calls stays under the per-call limit."""
        if not ollama_up:
            pytest.skip("Ollama not running")

        from config import Config
        client = _make_client()
        times: list[float] = []
        for i in range(3):
            elapsed, _ = _timed_chat(client, Config.OLLAMA_MODEL, _simple_messages())
            times.append(elapsed)
            print(f"\n[perf] call {i + 1}/3: {elapsed:.2f}s")

        avg = sum(times) / len(times)
        print(f"[perf] average: {avg:.2f}s  min: {min(times):.2f}s  max: {max(times):.2f}s")
        assert avg < _LIMIT, (
            f"Average response {avg:.1f}s exceeds limit of {_LIMIT}s"
        )

    def test_no_tools_faster_than_with_tools(self, ollama_up):
        """Sanity check: a message with no tools is generally not slower than one with tools.

        This is not a hard requirement (caching can invert it), so we only
        print the comparison rather than asserting a specific ratio.
        """
        if not ollama_up:
            pytest.skip("Ollama not running")

        from ai.assistant import _SHOPPING_TOOLS
        from config import Config
        client = _make_client()

        t_no_tools, _ = _timed_chat(client, Config.OLLAMA_MODEL, _simple_messages())
        messages_with_tools = [
            {"role": "system", "content": "ענה בעברית."},
            {"role": "user", "content": "שלום"},
        ]
        t_with_tools, _ = _timed_chat(
            client, Config.OLLAMA_MODEL, messages_with_tools, tools=_SHOPPING_TOOLS
        )

        print(
            f"\n[perf] no-tools: {t_no_tools:.2f}s  with-tools: {t_with_tools:.2f}s"
        )
        # Both must be within the time limit — the comparison is informational
        assert t_no_tools < _LIMIT
        assert t_with_tools < _LIMIT
