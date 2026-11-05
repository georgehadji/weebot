"""Score a long_context sample: every comma-separated part of expected_answer must appear in
the final assistant reply (whitespace-insensitive). 1.0 or 0.0."""


def evaluate(session, expected_answer: str) -> float:
    parts = [p.strip() for p in (expected_answer or "").split(",") if p.strip()]
    if not parts:
        return 0.0
    for event in reversed(session.events):
        message = getattr(event, "message", "")
        if getattr(event, "role", None) == "assistant" and message:
            reply = "".join(message.split())
            return 1.0 if all("".join(p.split()) in reply for p in parts) else 0.0
    return 0.0
