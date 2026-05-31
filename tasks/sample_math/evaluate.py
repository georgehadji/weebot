"""Custom scorer for sample_math benchmark task.

Returns 1.0 if the expected numeric answer appears in the last assistant message,
0.0 otherwise.
"""


def evaluate(session, expected_answer: str) -> float:
    """Score the session by checking for expected_answer in the final assistant reply."""
    if not expected_answer:
        return 0.5

    for event in reversed(session.events):
        role = getattr(event, "role", None)
        message = getattr(event, "message", "")
        if role == "assistant" and message:
            return 1.0 if str(expected_answer).strip() in message else 0.0

    return 0.0
