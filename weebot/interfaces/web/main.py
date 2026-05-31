"""FastAPI web server for weebot."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from weebot.application.di import Container
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.interfaces.web.routers import sessions_router, models_router, health_router, dashboard_router, behavior_router
from weebot.interfaces.web.routers.chat_router import router as chat_router
from weebot.interfaces.web.websocket import manager

logger = logging.getLogger(__name__)


# HTML for WebSocket testing (served at root)
WEBSOCKET_TEST_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Weebot Web UI</title>
    <style>
        body { font-family: system-ui, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; }
        h1 { color: #333; }
        .status { padding: 10px; border-radius: 4px; margin: 10px 0; }
        .connected { background: #d4edda; color: #155724; }
        .disconnected { background: #f8d7da; color: #721c24; }
        #messages { border: 1px solid #ddd; padding: 10px; height: 300px; overflow-y: auto; margin: 20px 0; }
        .message { padding: 5px; margin: 5px 0; border-bottom: 1px solid #eee; }
        input, button { padding: 10px; margin: 5px; }
    </style>
</head>
<body>
    <h1>🤖 Weebot Web UI</h1>
    <p>Backend is running. WebSocket test interface below:</p>
    
    <div id="status" class="status disconnected">Disconnected</div>
    
    <div>
        <input type="text" id="sessionId" placeholder="Session ID (optional)" style="width: 300px;">
        <button onclick="connect()">Connect</button>
        <button onclick="disconnect()">Disconnect</button>
    </div>
    
    <div>
        <input type="text" id="messageInput" placeholder="Test message" style="width: 400px;">
        <button onclick="sendMessage()">Send</button>
    </div>
    
    <div id="messages"></div>
    
    <script>
        let ws = null;
        
        function connect() {
            const sessionId = document.getElementById('sessionId').value;
            const wsUrl = sessionId 
                ? `ws://${window.location.host}/ws/sessions/${sessionId}`
                : `ws://${window.location.host}/ws`;
            
            ws = new WebSocket(wsUrl);
            
            ws.onopen = () => {
                document.getElementById('status').textContent = 'Connected';
                document.getElementById('status').className = 'status connected';
                addMessage('System', 'Connected to WebSocket');
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                addMessage('Received', JSON.stringify(data, null, 2));
            };
            
            ws.onclose = () => {
                document.getElementById('status').textContent = 'Disconnected';
                document.getElementById('status').className = 'status disconnected';
                addMessage('System', 'Disconnected from WebSocket');
            };
            
            ws.onerror = (error) => {
                addMessage('Error', error.toString());
            };
        }
        
        function disconnect() {
            if (ws) {
                ws.close();
                ws = null;
            }
        }
        
        function sendMessage() {
            if (!ws || ws.readyState !== WebSocket.OPEN) {
                alert('Not connected');
                return;
            }
            const message = document.getElementById('messageInput').value;
            ws.send(JSON.stringify({ type: 'test', message }));
            addMessage('Sent', message);
        }
        
        function addMessage(type, content) {
            const div = document.createElement('div');
            div.className = 'message';
            div.innerHTML = `<strong>${type}:</strong> <pre>${content}</pre>`;
            document.getElementById('messages').appendChild(div);
            document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
        }
    </script>
</body>
</html>
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    logger.info("Starting Weebot Web Server...")
    container = Container()
    container.configure_defaults()
    app.state.container = container
    yield
    logger.info("Shutting down Weebot Web Server...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Weebot API",
        description="Production-grade AI agent framework with real-time event streaming",
        version="2.6.0",
        lifespan=lifespan,
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "*",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(sessions_router, prefix="/api")
    app.include_router(models_router, prefix="/api")
    app.include_router(health_router, prefix="/api")
    app.include_router(dashboard_router, prefix="/api")
    app.include_router(behavior_router, prefix="/api")
    app.include_router(chat_router)
    
    # Root endpoint - WebSocket test UI
    @app.get("/", response_class=HTMLResponse)
    async def root() -> str:
        """Serve WebSocket test UI."""
        return WEBSOCKET_TEST_HTML
    
    # WebSocket endpoints - must be defined before CORS middleware to avoid conflicts
    @app.websocket("/ws")
    async def websocket_global(websocket: WebSocket) -> None:
        """Global WebSocket connection (receives all events)."""
        client_host = websocket.client.host if websocket.client else "unknown"
        logger.info(f"WebSocket /ws connection from {client_host}")
        
        await manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                logger.debug(f"Received: {data}")
        except WebSocketDisconnect:
            logger.info(f"WebSocket /ws disconnected from {client_host}")
        except Exception as e:
            logger.warning(f"WebSocket /ws error: {e}")
        finally:
            await manager.disconnect(websocket)
    
    @app.websocket("/ws/sessions/{session_id}")
    async def websocket_session(websocket: WebSocket, session_id: str) -> None:
        """Session-specific WebSocket connection."""
        client_host = websocket.client.host if websocket.client else "unknown"
        logger.info(f"WebSocket /ws/sessions/{session_id} connection from {client_host}")
        
        await manager.connect(websocket, session_id)
        try:
            while True:
                data = await websocket.receive_text()
                logger.debug(f"Received for session {session_id}: {data}")
        except WebSocketDisconnect:
            logger.info(f"WebSocket /ws/sessions/{session_id} disconnected from {client_host}")
        except Exception as e:
            logger.warning(f"WebSocket /ws/sessions/{session_id} error: {e}")
        finally:
            await manager.disconnect(websocket, session_id)
    
    # Serve static files if they exist (for production build)
    static_dir = Path(__file__).parent.parent.parent.parent / "weebot-ui" / "dist"
    if static_dir.exists():
        app.mount("/app", StaticFiles(directory=str(static_dir), html=True), name="app")
    
    return app


# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("WEEBOT_PORT", "8000"))
    host = os.getenv("WEEBOT_HOST", "0.0.0.0")
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    uvicorn.run(
        "weebot.interfaces.web.main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info",
    )
