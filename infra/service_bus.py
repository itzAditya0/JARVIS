"""
FastAPI Service Bus
-------------------
Internal API for module communication.
Provides REST endpoints for orchestrator control.

This is NOT an external-facing API - it's for internal service communication.
"""

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional
import asyncio
import logging
import os

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# Request/Response Models

class TextCommand(BaseModel):
    """Text command input."""
    text: str = Field(..., description="Command text to process")
    context: Optional[str] = Field(None, description="Optional context")


class CommandResponse(BaseModel):
    """Response from command processing."""
    success: bool
    command_id: str
    output: Optional[str] = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class StatusResponse(BaseModel):
    """System status response."""
    state: str
    mode: str
    stt_loaded: bool
    commands_loaded: int
    tools_loaded: int
    memory_turns: int
    uptime_seconds: float


class MemoryStats(BaseModel):
    """Memory statistics."""
    turns: int
    estimated_tokens: int
    max_turns: int
    max_tokens: int
    preferences_count: int


class ToolInfo(BaseModel):
    """Tool information."""
    name: str
    description: str
    permission: str
    category: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str = "0.1.0"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# Service Bus

class ServiceBus:
    """
    Internal service bus for JARVIS.
    
    Provides REST API for:
    - Command processing
    - Status queries
    - Memory management
    - Tool information
    """
    
    def __init__(self, orchestrator=None):
        self._orchestrator = orchestrator
        self._start_time = datetime.now()
        self._logger = logging.getLogger("jarvis.infra.service_bus")
        self._app: Optional[FastAPI] = None
    
    def set_orchestrator(self, orchestrator) -> None:
        """Set the orchestrator instance."""
        self._orchestrator = orchestrator
    
    def create_app(self) -> FastAPI:
        """Create and configure the FastAPI application."""
        
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            self._logger.info("Service bus starting...")
            yield
            self._logger.info("Service bus shutting down...")
        
        app = FastAPI(
            title="JARVIS Internal API",
            description="Internal service bus for JARVIS modules",
            version="0.1.0",
            lifespan=lifespan
        )
        
        # CORS for local development
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:*", "http://127.0.0.1:*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Register routes
        self._register_routes(app)
        
        self._app = app
        return app
    
    def _register_routes(self, app: FastAPI) -> None:
        """Register all API routes."""
        
        @app.get("/health", response_model=HealthResponse, tags=["System"])
        async def health_check():
            """Health check endpoint."""
            return HealthResponse(status="healthy")
        
        @app.get("/status", response_model=StatusResponse, tags=["System"])
        async def get_status():
            """Get system status."""
            if not self._orchestrator:
                raise HTTPException(status_code=503, detail="Orchestrator not initialized")
            
            status = self._orchestrator.get_status()
            uptime = (datetime.now() - self._start_time).total_seconds()
            
            return StatusResponse(
                state=status.get("state", "UNKNOWN"),
                mode=status.get("mode", "deterministic"),
                stt_loaded=status.get("stt_loaded", False),
                commands_loaded=status.get("commands_loaded", 0),
                tools_loaded=status.get("tools_loaded", 0),
                memory_turns=status.get("memory_turns", 0),
                uptime_seconds=uptime
            )
        
        @app.post("/command", response_model=CommandResponse, tags=["Commands"])
        async def process_command(cmd: TextCommand):
            """Process a text command."""
            if not self._orchestrator:
                raise HTTPException(status_code=503, detail="Orchestrator not initialized")
            
            start_time = datetime.now()
            
            try:
                result = self._orchestrator.process_text_directly(cmd.text)
                execution_time = (datetime.now() - start_time).total_seconds() * 1000
                
                return CommandResponse(
                    success=True,
                    command_id="processed",
                    output=result,
                    execution_time_ms=execution_time
                )
            except Exception as e:
                self._logger.error(f"Command processing error: {e}")
                return CommandResponse(
                    success=False,
                    command_id="error",
                    error=str(e)
                )
        
        @app.get("/memory", response_model=MemoryStats, tags=["Memory"])
        async def get_memory_stats():
            """Get memory statistics."""
            if not self._orchestrator:
                raise HTTPException(status_code=503, detail="Orchestrator not initialized")
            
            if not hasattr(self._orchestrator, 'get_memory_stats'):
                raise HTTPException(status_code=400, detail="Memory not enabled")
            
            stats = self._orchestrator.get_memory_stats()
            return MemoryStats(**stats)
        
        @app.delete("/memory", tags=["Memory"])
        async def clear_memory():
            """Clear conversation memory."""
            if not self._orchestrator:
                raise HTTPException(status_code=503, detail="Orchestrator not initialized")
            
            if not hasattr(self._orchestrator, 'clear_memory'):
                raise HTTPException(status_code=400, detail="Memory not enabled")
            
            count = self._orchestrator.clear_memory()
            return {"cleared": count}
        
        @app.get("/memory/summary", tags=["Memory"])
        async def get_memory_summary():
            """Get conversation summary."""
            if not self._orchestrator:
                raise HTTPException(status_code=503, detail="Orchestrator not initialized")
            
            if not hasattr(self._orchestrator, 'get_conversation_summary'):
                raise HTTPException(status_code=400, detail="Memory not enabled")
            
            return {"summary": self._orchestrator.get_conversation_summary()}
        
        @app.get("/tools", response_model=List[ToolInfo], tags=["Tools"])
        async def list_tools():
            """List available tools."""
            if not self._orchestrator:
                raise HTTPException(status_code=503, detail="Orchestrator not initialized")
            
            if not hasattr(self._orchestrator, '_tool_registry'):
                raise HTTPException(status_code=400, detail="Tools not enabled")
            
            registry = self._orchestrator._tool_registry
            if not registry:
                return []
            
            tools = []
            for tool in registry.list_tools():
                tools.append(ToolInfo(
                    name=tool.name,
                    description=tool.description,
                    permission=tool.permission.value,
                    category=tool.category
                ))
            return tools
        
        @app.post("/mode/{mode}", tags=["System"])
        async def set_mode(mode: str):
            """Switch between deterministic and LLM mode."""
            if not self._orchestrator:
                raise HTTPException(status_code=503, detail="Orchestrator not initialized")
            
            if mode not in ("deterministic", "llm"):
                raise HTTPException(status_code=400, detail="Invalid mode")
            
            if hasattr(self._orchestrator, 'set_mode'):
                self._orchestrator.set_mode(mode)
                return {"mode": mode}
            else:
                raise HTTPException(status_code=400, detail="Mode switching not supported")
        
        @app.get("/preferences", tags=["Preferences"])
        async def list_preferences():
            """List all preferences."""
            if not self._orchestrator:
                raise HTTPException(status_code=503, detail="Orchestrator not initialized")
            
            if not hasattr(self._orchestrator, 'list_preferences'):
                raise HTTPException(status_code=400, detail="Preferences not enabled")
            
            return self._orchestrator.list_preferences()
        
        @app.put("/preferences/{key}", tags=["Preferences"])
        async def set_preference(key: str, value: str):
            """Set a preference."""
            if not self._orchestrator:
                raise HTTPException(status_code=503, detail="Orchestrator not initialized")
            
            if not hasattr(self._orchestrator, 'set_preference'):
                raise HTTPException(status_code=400, detail="Preferences not enabled")
            
            self._orchestrator.set_preference(key, value)
            return {"key": key, "value": value}


def create_app(orchestrator=None) -> FastAPI:
    """Create the FastAPI application."""
    bus = ServiceBus(orchestrator)
    return bus.create_app()


async def run_server(app: FastAPI, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the service bus server."""
    import uvicorn
    
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    import uvicorn
    
    # Create app without orchestrator for testing
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=8000)
