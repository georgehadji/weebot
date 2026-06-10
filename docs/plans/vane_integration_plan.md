# Implementation Plan: Vane (Perplexica) Integration for Weebot

## 1. Objective
Integrate the **Vane** (formerly Perplexica) AI answering engine into Weebot to provide agents with high-quality, cited research capabilities. This integration will allow Weebot to move beyond simple keyword search to full-context answering.

## 2. Infrastructure Prerequisites
- **Vane Instance**: A self-hosted Vane instance (Docker recommended) running on a reachable network.
- **API Connectivity**: Weebot must have network access to the Vane API port (default: 3000).

## 3. Implementation Steps

### Phase 1: Configuration & Environment
1.  **Update `weebot/config/settings.py`**:
    - Add `vane_base_url: str = "http://localhost:3000"` to the `WeebotSettings` class.
    - Add a validator to ensure the URL is well-formed.
2.  **Update `.env`**:
    - Add `VANE_BASE_URL=http://localhost:3000` to the local environment.

### Phase 2: Tool Development
1.  **Create `weebot/tools/vane_search.py`**:
    - Implement `VaneSearchTool(BaseTool)`.
    - **Parameters**:
        - `query` (string, required): The research question.
        - `focus_mode` (string, optional): One of `webSearch`, `academicSearch`, `redditSearch`, `youtubeSearch`. Defaults to `webSearch`.
        - `optimization` (string, optional): `speed`, `balanced`, or `quality`. Defaults to `balanced`.
    - **Logic**:
        - Send a POST request to `/api/search`.
        - Parse the `message` (the synthesized answer) and `sources` (citations).
        - Format the output as a `ToolResult` with the citations stored in metadata for traceability.

### Phase 3: Registration & Routing
1.  **Update `weebot/tools/tool_registry.py`**:
    - Import and register `vane_search` in the global tool map.
    - Assign the tool to the `RESEARCH` and `ADMIN` roles.
2.  **Heuristic Optimization**:
    - Update the `HeuristicRouter` to suggest `vane_search` when keywords like "cite," "paper," "academic," or "comprehensive research" are detected in the task description.

### Phase 4: Verification & Testing
1.  **Unit Tests**:
    - Mock the Vane API response using `httpx` to verify parsing logic.
2.  **Integration Test**:
    - Create a test script in `tests/integration/test_vane_integration.py` to perform a live search if a Vane instance is detected.
3.  **Validation**:
    - Ensure the citations are correctly rendered in Weebot's UI/logs.

## 4. Safety Considerations
- **Content Filtering**: Vane's output should be treated as untrusted text and sanitized before being used in any `bash` or `python` tool calls.
- **Timeout Management**: Vane's "Quality" mode can take 10-20 seconds; the tool timeout must be set accordingly (default to 30s).

## 5. Success Criteria
- The agent can successfully call `vane_search` and receive a cited response.
- The agent prefers `vane_search` over `web_search` for complex inquiries.
- Citations are preserved and viewable in the session audit logs.
