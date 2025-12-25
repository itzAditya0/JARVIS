#!/usr/bin/env python3
"""
JARVIS Service Bus Server
-------------------------
Runs the FastAPI service bus with an orchestrator.

Usage:
    python -m infra.server --port 8000
    python -m infra.server --memory --mock-llm
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn
from rich.console import Console

from infra.service_bus import ServiceBus

console = Console()


def main():
    parser = argparse.ArgumentParser(description="JARVIS Service Bus Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--memory", action="store_true", help="Enable memory (Phase 3)")
    parser.add_argument("--mock-llm", action="store_true", help="Use mock LLM")
    parser.add_argument("--llm", action="store_true", help="Use real LLM")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Create orchestrator
    console.print("[dim]Creating orchestrator...[/dim]")
    
    if args.memory:
        from core import Phase3Orchestrator, Phase3Config
        config = Phase3Config(
            mode="llm",
            use_mock_llm=args.mock_llm or not args.llm
        )
        orchestrator = Phase3Orchestrator(config)
        console.print("[green]Using Phase 3 orchestrator with memory[/green]")
    elif args.llm or args.mock_llm:
        from core import Phase2Orchestrator, Phase2Config
        config = Phase2Config(
            mode="llm",
            use_mock_llm=args.mock_llm or not args.llm
        )
        orchestrator = Phase2Orchestrator(config)
        console.print("[green]Using Phase 2 orchestrator[/green]")
    else:
        from core import Orchestrator
        from core.orchestrator import OrchestratorConfig
        config = OrchestratorConfig()
        orchestrator = Orchestrator(config)
        console.print("[yellow]Using Phase 1 orchestrator[/yellow]")
    
    # Initialize
    console.print("[dim]Initializing...[/dim]")
    orchestrator.initialize()
    
    # Create service bus
    bus = ServiceBus(orchestrator)
    app = bus.create_app()
    
    console.print(f"\n[bold green]JARVIS Service Bus[/bold green]")
    console.print(f"Running on http://{args.host}:{args.port}")
    console.print(f"API docs: http://{args.host}:{args.port}/docs")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")
    
    # Run server
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level.lower()
    )
    
    # Cleanup
    orchestrator.shutdown()


if __name__ == "__main__":
    main()
