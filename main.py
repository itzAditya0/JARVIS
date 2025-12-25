#!/usr/bin/env python3
"""
JARVIS - Voice-Driven Tool-Orchestrated Automation System
==========================================================

Main entry point for the JARVIS assistant.

Usage:
    python main.py              # Interactive mode with push-to-talk (deterministic)
    python main.py --test       # Test mode with text input
    python main.py --llm        # Use LLM-based planning
    python main.py --help       # Show help

Phase 1: Deterministic command matching
Phase 2: LLM-based task planning
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from pynput import keyboard
except ImportError:
    keyboard = None

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.logging import RichHandler

from core import (
    Orchestrator, State,
    Phase2Orchestrator, Phase2Config,
    Phase3Orchestrator, Phase3Config,
    Phase4Orchestrator, Phase4Config
)
from core.orchestrator import CommandResult, OrchestratorConfig


# Setup rich console
console = Console()


def setup_logging(level: str = "INFO") -> None:
    """Configure logging with rich output."""
    # Create logs directory
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_path=False
            ),
            logging.FileHandler(
                logs_dir / f"jarvis_{datetime.now().strftime('%Y%m%d')}.log"
            )
        ]
    )


def print_banner(mode: str = "deterministic", memory: bool = False) -> None:
    """Print the JARVIS banner."""
    banner = Text()
    banner.append("JARVIS", style="bold cyan")
    banner.append(" - Voice-Driven Automation System\n", style="dim")
    
    # Show mode info
    if memory:
        banner.append("Mode: LLM + Memory\n\n", style="green")
    elif mode == "llm":
        banner.append("Mode: LLM Planning\n\n", style="green")
    else:
        banner.append("Mode: Deterministic\n\n", style="yellow")
    
    banner.append("Press ", style="dim")
    banner.append("SPACE", style="bold green")
    banner.append(" to speak | ", style="dim")
    banner.append("ESC", style="bold red")
    banner.append(" to quit", style="dim")
    
    console.print(Panel(banner, title="Welcome", border_style="blue"))


def print_status(orchestrator) -> None:
    """Print current system status."""
    status = orchestrator.get_status()
    mode = status.get('mode', 'deterministic')
    mode_str = f"Mode: {mode} | " if 'mode' in status else ""
    tools_str = f"Tools: {status.get('tools_loaded', 0)} | " if 'tools_loaded' in status else ""
    
    console.print(f"[dim]{mode_str}State: {status['state']} | "
                  f"STT: {'✓' if status['stt_loaded'] else '○'} | "
                  f"Commands: {status['commands_loaded']} | {tools_str.rstrip(' | ')}[/dim]")


def on_transcription(text: str, confidence: float) -> None:
    """Callback for transcription events."""
    console.print(f"\n[bold blue]You said:[/bold blue] {text}")
    console.print(f"[dim]Confidence: {confidence:.1%}[/dim]")


def on_command(command_id: str, args: dict) -> None:
    """Callback for command match events."""
    console.print(f"[bold yellow]Command:[/bold yellow] {command_id}")
    if args:
        console.print(f"[dim]Arguments: {args}[/dim]")


def on_result(result: CommandResult) -> None:
    """Callback for command result events."""
    if result.success:
        console.print(f"[bold green]Result:[/bold green] {result.output}")
    else:
        console.print(f"[bold red]Error:[/bold red] {result.error}")
    
    if result.execution_time_ms > 0:
        console.print(f"[dim]Execution time: {result.execution_time_ms:.1f}ms[/dim]")


def run_interactive(orchestrator, mode: str = "deterministic", memory: bool = False) -> None:
    """Run in interactive mode with push-to-talk."""
    if keyboard is None:
        console.print("[red]Error: pynput is required for interactive mode.[/red]")
        console.print("Install with: pip install pynput")
        console.print("\nFalling back to text mode. Type 'quit' to exit.")
        run_text_mode(orchestrator, mode)
        return
    
    print_banner(mode, memory=memory)
    print_status(orchestrator)
    
    is_recording = False
    should_quit = False
    
    def on_press(key):
        nonlocal is_recording
        
        try:
            if key == keyboard.Key.space and not is_recording:
                is_recording = True
                console.print("\n[green]● Recording...[/green] (release SPACE to stop)")
                orchestrator.start_listening()
        except Exception as e:
            logging.error(f"Key press error: {e}")
    
    def on_release(key):
        nonlocal is_recording, should_quit
        
        try:
            if key == keyboard.Key.space and is_recording:
                is_recording = False
                console.print("[yellow]○ Processing...[/yellow]")
                orchestrator.stop_listening()
                print_status(orchestrator)
            
            elif key == keyboard.Key.esc:
                should_quit = True
                return False  # Stop listener
                
        except Exception as e:
            logging.error(f"Key release error: {e}")
    
    # Start keyboard listener
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    
    console.print("\n[dim]Ready. Hold SPACE to speak...[/dim]")
    
    try:
        while not should_quit:
            listener.join(timeout=0.1)
            if not listener.is_alive():
                break
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        console.print("\n[yellow]Shutting down...[/yellow]")
        orchestrator.shutdown()


def run_text_mode(orchestrator, mode: str = "deterministic") -> None:
    """Run in text input mode (for testing)."""
    mode_label = "LLM Mode" if mode == "llm" else "Deterministic Mode"
    console.print(Panel(
        f"Text Input Mode ({mode_label})\nType commands to test. Type 'quit' to exit.\nType 'mode' to switch modes.",
        title="JARVIS Test Mode",
        border_style="green" if mode == "llm" else "yellow"
    ))
    
    print_status(orchestrator)
    
    while True:
        try:
            text = console.input("\n[bold cyan]>[/bold cyan] ").strip()
            
            if not text:
                continue
            
            if text.lower() in ("quit", "exit", "q"):
                break
            
            if text.lower() == "status":
                print_status(orchestrator)
                continue
            
            if text.lower() == "mode":
                # Toggle mode if using Phase2Orchestrator
                if hasattr(orchestrator, 'set_mode'):
                    current = orchestrator.phase2_config.mode
                    new_mode = "deterministic" if current == "llm" else "llm"
                    orchestrator.set_mode(new_mode)
                    console.print(f"[green]Switched to {new_mode} mode[/green]")
                else:
                    console.print("[yellow]Mode switching requires --llm flag[/yellow]")
                continue
            
            if text.lower() == "tools":
                if hasattr(orchestrator, 'get_available_tools'):
                    tools = orchestrator.get_available_tools()
                    console.print(f"[bold]Available tools:[/bold] {', '.join(tools)}")
                else:
                    console.print("[yellow]Tools require --llm flag[/yellow]")
                continue
            
            if text.lower() == "help":
                console.print("""
[bold]Available commands:[/bold]
  - what time is it
  - what's the date
  - search for [query]
  - open [app name]
  - list files
  - volume up/down
  
[bold]System commands:[/bold]
  - help      (show this)
  - status    (show system status)
  - mode      (toggle deterministic/LLM mode)
  - tools     (list available tools)
  - quit      (exit)

[bold]Memory commands (Phase 3):[/bold]
  - memory    (show memory stats)
  - history   (show conversation summary)
  - clear     (clear conversation history)
  - prefs     (list preferences)
""")
                continue
            
            # Phase 3: Memory commands
            if text.lower() == "memory":
                if hasattr(orchestrator, 'get_memory_stats'):
                    stats = orchestrator.get_memory_stats()
                    console.print(f"[bold]Memory Stats:[/bold]")
                    for k, v in stats.items():
                        console.print(f"  {k}: {v}")
                else:
                    console.print("[yellow]Memory requires --memory flag[/yellow]")
                continue
            
            if text.lower() == "history":
                if hasattr(orchestrator, 'get_conversation_summary'):
                    summary = orchestrator.get_conversation_summary()
                    console.print(f"[bold]Conversation Summary:[/bold] {summary}")
                else:
                    console.print("[yellow]History requires --memory flag[/yellow]")
                continue
            
            if text.lower() == "clear":
                if hasattr(orchestrator, 'clear_memory'):
                    count = orchestrator.clear_memory()
                    console.print(f"[green]Cleared {count} turns from memory[/green]")
                else:
                    console.print("[yellow]Clear requires --memory flag[/yellow]")
                continue
            
            if text.lower() == "prefs":
                if hasattr(orchestrator, 'list_preferences'):
                    prefs = orchestrator.list_preferences()
                    console.print(f"[bold]Preferences:[/bold]")
                    for k, v in prefs.items():
                        console.print(f"  {k}: {v}")
                else:
                    console.print("[yellow]Preferences require --memory flag[/yellow]")
                continue
            
            # Process the text command
            result = orchestrator.process_text_directly(text)
            
        except KeyboardInterrupt:
            break
        except EOFError:
            break
    
    console.print("\n[yellow]Shutting down...[/yellow]")
    orchestrator.shutdown()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="JARVIS - Voice-Driven Automation System"
    )
    parser.add_argument(
        "--test", "-t",
        action="store_true",
        help="Run in text input mode (no audio)"
    )
    parser.add_argument(
        "--basic",
        action="store_true",
        help="Use basic deterministic mode only (Phase 1)"
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Disable conversation memory"
    )
    parser.add_argument(
        "--mock-llm",
        action="store_true",
        help="Use mock LLM for testing (no API key needed)"
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to configuration file"
    )
    parser.add_argument(
        "--log-level", "-l",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level"
    )
    
    # Legacy flags (hidden but still work)
    parser.add_argument("--llm", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--memory", action="store_true", help=argparse.SUPPRESS)
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger("jarvis.main")
    
    try:
        # Determine mode - Phase 4 with multimodal is now the default
        use_basic = args.basic
        use_memory = not args.no_memory and not use_basic
        use_llm = not use_basic
        use_mock = args.mock_llm
        
        mode = "deterministic" if use_basic else "llm"
        
        # Create appropriate orchestrator
        if use_memory:
            # Phase 4: Full multimodal orchestrator (DEFAULT)
            config = Phase4Config(
                config_path=args.config,
                mode="llm",
                use_mock_llm=use_mock
            )
            orchestrator = Phase4Orchestrator(config)
            console.print(f"[green]JARVIS (Multimodal) - {'mock' if use_mock else 'Gemini'}[/green]")
        elif use_llm:
            # Phase 2: LLM-based orchestrator
            config = Phase2Config(
                config_path=args.config,
                mode="llm",
                use_mock_llm=use_mock
            )
            orchestrator = Phase2Orchestrator(config)
            console.print(f"[green]JARVIS LLM Mode ({'mock' if use_mock else 'Gemini'})[/green]")
        else:
            # Phase 1: Deterministic orchestrator (--basic flag)
            config = OrchestratorConfig(config_path=args.config)
            orchestrator = Orchestrator(config)
            console.print("[yellow]JARVIS Basic Mode (deterministic only)[/yellow]")
        # Register callbacks
        orchestrator.on_transcription(on_transcription)
        orchestrator.on_command(on_command)
        orchestrator.on_result(on_result)
        
        # Initialize subsystems
        console.print("[dim]Initializing JARVIS...[/dim]")
        orchestrator.initialize()
        
        # Run appropriate mode
        if args.test:
            run_text_mode(orchestrator, mode)
        else:
            run_interactive(orchestrator, mode, memory=args.memory)
        
        return 0
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        return 130
    except Exception as e:
        logger.exception("Fatal error")
        console.print(f"[bold red]Error:[/bold red] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
