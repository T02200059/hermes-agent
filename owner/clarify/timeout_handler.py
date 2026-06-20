"""Clarify timeout handler.

Called from the official agent execution paths when a ``clarify`` prompt times
out or is cancelled by a session-boundary cleanup. The handler interrupts the
agent loop and returns a synthetic tool result so the conversation history
remains well-formed (every assistant tool_call has a matching tool result).
"""

from typing import Any


# Synthetic tool result returned to the model when clarify stops due to timeout.
# The agent loop detects the interrupt flag on the next iteration and exits.
CLARIFY_TIMEOUT_RESULT = "[Clarify timed out after user inactivity — stopping agent]"


def handle_clarify_timeout(agent: Any, tool_call_id: str = "") -> str:
    """Stop the agent and return a synthetic tool result for a clarify timeout.

    Args:
        agent: The running ``AIAgent`` instance.
        tool_call_id: The OpenAI tool_call_id associated with the clarify call.
                      Kept in the signature for future extensions (e.g.
                      per-tool-call telemetry) but not required for the
                      current interrupt-based implementation.

    Returns:
        A synthetic string that will be appended as the tool result message.
    """
    try:
        agent.interrupt("clarify timed out")
    except Exception:
        # Interrupt is best-effort; never let a signalling failure mask the
        # timeout stop decision.
        pass
    return CLARIFY_TIMEOUT_RESULT
