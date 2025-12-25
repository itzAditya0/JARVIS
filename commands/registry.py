"""
Command Registry
----------------
Deterministic command matching from user text.
No LLM logic. No OS execution. Only pattern matching.

Exit Criterion: Every command is auditable without running the system.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
import re
import yaml


@dataclass
class CommandArgument:
    """Definition of a command argument."""
    name: str
    type: str
    required: bool = True
    default: Optional[Any] = None


@dataclass
class CommandDefinition:
    """Definition of a command from the registry."""
    id: str
    name: str
    patterns: List[str]
    permission: str
    description: str
    args: List[CommandArgument] = field(default_factory=list)
    
    def __repr__(self) -> str:
        return f"CommandDefinition(id={self.id}, name={self.name})"


@dataclass
class CommandIntent:
    """
    Result of matching user text to a command.
    Contains command ID and extracted arguments.
    """
    command_id: str
    command_name: str
    args: Dict[str, Any]
    permission: str
    confidence: float  # 0.0 - 1.0
    matched_pattern: str
    original_text: str
    
    @property
    def is_match(self) -> bool:
        """Check if this is a valid match."""
        return self.confidence > 0.0
    
    def __repr__(self) -> str:
        return (
            f"CommandIntent(id={self.command_id}, "
            f"args={self.args}, confidence={self.confidence:.2f})"
        )


class CommandRegistry:
    """
    Registry for command definitions with pattern matching.
    
    Responsibilities:
    - Load command definitions from YAML
    - Match user text to commands
    - Extract arguments from patterns
    
    Forbidden:
    - Any LLM logic
    - Any OS execution
    """
    
    def __init__(self, registry_path: Optional[str] = None):
        self._commands: Dict[str, CommandDefinition] = {}
        self._patterns: List[tuple] = []  # (compiled_regex, command_id, pattern_str)
        
        if registry_path:
            self.load(registry_path)
    
    def load(self, registry_path: str) -> None:
        """Load command definitions from a YAML file."""
        path = Path(registry_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Command registry not found: {registry_path}")
        
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        
        commands = data.get('commands', [])
        
        for cmd_data in commands:
            # Parse arguments
            args = []
            for arg_data in cmd_data.get('args', []):
                args.append(CommandArgument(
                    name=arg_data['name'],
                    type=arg_data.get('type', 'string'),
                    required=arg_data.get('required', True),
                    default=arg_data.get('default')
                ))
            
            # Create command definition
            cmd = CommandDefinition(
                id=cmd_data['id'],
                name=cmd_data['name'],
                patterns=cmd_data['patterns'],
                permission=cmd_data['permission'],
                description=cmd_data['description'],
                args=args
            )
            
            self._commands[cmd.id] = cmd
            
            # Compile patterns to regex
            for pattern in cmd.patterns:
                regex = self._pattern_to_regex(pattern)
                self._patterns.append((regex, cmd.id, pattern))
    
    def _pattern_to_regex(self, pattern: str) -> re.Pattern:
        """
        Convert a pattern string to a compiled regex.
        Patterns like "search for {query}" become "search for (?P<query>.+)"
        """
        # Escape special regex characters except our placeholders
        escaped = re.escape(pattern)
        
        # Convert {arg_name} placeholders to named capture groups
        # The escaped version will be \{arg_name\}
        regex_pattern = re.sub(
            r'\\{(\w+)\\}',
            r'(?P<\1>.+?)',
            escaped
        )
        
        # Make it match the full string (with optional surrounding whitespace)
        regex_pattern = f'^\\s*{regex_pattern}\\s*$'
        
        return re.compile(regex_pattern, re.IGNORECASE)
    
    def match(self, text: str) -> CommandIntent:
        """
        Match user text to a command.
        
        Returns a CommandIntent with confidence 0.0 if no match found.
        """
        text = text.strip().lower()
        
        if not text:
            return CommandIntent(
                command_id="",
                command_name="",
                args={},
                permission="",
                confidence=0.0,
                matched_pattern="",
                original_text=text
            )
        
        best_match = None
        best_confidence = 0.0
        
        for regex, command_id, pattern in self._patterns:
            match = regex.match(text)
            
            if match:
                # Extract named groups as arguments
                args = {k: v for k, v in match.groupdict().items() if v is not None}
                
                # Calculate confidence based on match quality
                # Exact matches get 1.0, partial matches get lower scores
                pattern_words = len(pattern.split())
                text_words = len(text.split())
                
                # Higher confidence for closer word count match
                word_ratio = min(pattern_words, text_words) / max(pattern_words, text_words)
                confidence = 0.7 + (0.3 * word_ratio)
                
                if confidence > best_confidence:
                    cmd = self._commands[command_id]
                    best_match = CommandIntent(
                        command_id=command_id,
                        command_name=cmd.name,
                        args=args,
                        permission=cmd.permission,
                        confidence=confidence,
                        matched_pattern=pattern,
                        original_text=text
                    )
                    best_confidence = confidence
        
        if best_match:
            return best_match
        
        # No match found
        return CommandIntent(
            command_id="",
            command_name="",
            args={},
            permission="",
            confidence=0.0,
            matched_pattern="",
            original_text=text
        )
    
    def get_command(self, command_id: str) -> Optional[CommandDefinition]:
        """Get a command definition by ID."""
        return self._commands.get(command_id)
    
    def list_commands(self) -> List[CommandDefinition]:
        """List all registered commands."""
        return list(self._commands.values())
    
    def list_commands_by_permission(self, permission: str) -> List[CommandDefinition]:
        """List commands filtered by permission level."""
        return [
            cmd for cmd in self._commands.values()
            if cmd.permission == permission
        ]
    
    def __len__(self) -> int:
        return len(self._commands)
    
    def __contains__(self, command_id: str) -> bool:
        return command_id in self._commands


def test_registry(registry_path: str = "commands/command_map.yaml") -> None:
    """Test the command registry standalone."""
    print("Testing Command Registry...")
    
    registry = CommandRegistry(registry_path)
    print(f"Loaded {len(registry)} commands")
    
    # Test cases
    test_inputs = [
        "check system status",
        "open browser",
        "search for python tutorials",
        "what time is it",
        "open spotify",
        "volume up",
        "help",
        "this is not a command",
    ]
    
    print("\nTest Results:")
    print("-" * 60)
    
    for text in test_inputs:
        intent = registry.match(text)
        if intent.is_match:
            print(f"✓ '{text}'")
            print(f"  → {intent.command_id} (confidence: {intent.confidence:.2f})")
            if intent.args:
                print(f"  → args: {intent.args}")
        else:
            print(f"✗ '{text}' → No match")
        print()


if __name__ == "__main__":
    import sys
    registry_path = sys.argv[1] if len(sys.argv) > 1 else "commands/command_map.yaml"
    test_registry(registry_path)
