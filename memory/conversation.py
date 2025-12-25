"""
Conversation Memory
-------------------
Short-term conversational memory with fixed size.
Stores last N user turns and tool outputs.

Rules:
- Fixed size window
- Explicit pruning
- No auto-learning
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional
import json
import logging


class TurnRole(Enum):
    """Role in a conversation turn."""
    USER = auto()
    ASSISTANT = auto()
    TOOL = auto()
    SYSTEM = auto()


@dataclass
class ConversationTurn:
    """A single turn in the conversation."""
    role: TurnRole
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # For tool turns
    tool_name: Optional[str] = None
    tool_args: Optional[Dict] = None
    tool_result: Optional[Any] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "role": self.role.name.lower(),
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_result": str(self.tool_result) if self.tool_result else None
        }
    
    def to_llm_message(self) -> Dict:
        """Convert to LLM message format."""
        role_map = {
            TurnRole.USER: "user",
            TurnRole.ASSISTANT: "assistant",
            TurnRole.TOOL: "assistant",  # Tool results as assistant
            TurnRole.SYSTEM: "system"
        }
        
        return {
            "role": role_map[self.role],
            "content": self.content
        }
    
    @property
    def token_estimate(self) -> int:
        """Rough estimate of tokens (4 chars ≈ 1 token)."""
        base = len(self.content) // 4
        if self.tool_result:
            base += len(str(self.tool_result)) // 4
        return max(1, base)
    
    def __repr__(self) -> str:
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"Turn({self.role.name}: {preview})"


@dataclass
class ConversationMemory:
    """
    Short-term conversation memory.
    
    - Fixed size (max_turns)
    - Explicit eviction (oldest first)
    - Token budget enforcement
    """
    
    max_turns: int = 20
    max_tokens: int = 4000  # Rough token budget
    
    def __post_init__(self):
        self._turns: List[ConversationTurn] = []
        self._logger = logging.getLogger("jarvis.memory.conversation")
    
    def add_user_turn(self, content: str, metadata: Optional[Dict] = None) -> ConversationTurn:
        """Add a user message."""
        turn = ConversationTurn(
            role=TurnRole.USER,
            content=content,
            metadata=metadata or {}
        )
        self._add_turn(turn)
        return turn
    
    def add_assistant_turn(self, content: str, metadata: Optional[Dict] = None) -> ConversationTurn:
        """Add an assistant response."""
        turn = ConversationTurn(
            role=TurnRole.ASSISTANT,
            content=content,
            metadata=metadata or {}
        )
        self._add_turn(turn)
        return turn
    
    def add_tool_turn(
        self,
        tool_name: str,
        tool_args: Dict,
        tool_result: Any,
        metadata: Optional[Dict] = None
    ) -> ConversationTurn:
        """Add a tool execution result."""
        content = f"Tool {tool_name} returned: {tool_result}"
        turn = ConversationTurn(
            role=TurnRole.TOOL,
            content=content,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=tool_result,
            metadata=metadata or {}
        )
        self._add_turn(turn)
        return turn
    
    def add_system_turn(self, content: str) -> ConversationTurn:
        """Add a system message."""
        turn = ConversationTurn(
            role=TurnRole.SYSTEM,
            content=content
        )
        self._add_turn(turn)
        return turn
    
    def _add_turn(self, turn: ConversationTurn) -> None:
        """Add a turn and enforce limits."""
        self._turns.append(turn)
        self._enforce_limits()
        self._logger.debug(f"Added turn: {turn.role.name}, total: {len(self._turns)}")
    
    def _enforce_limits(self) -> None:
        """Enforce turn count and token limits."""
        # Remove oldest turns if exceeding max_turns
        while len(self._turns) > self.max_turns:
            removed = self._turns.pop(0)
            self._logger.debug(f"Evicted turn (count limit): {removed}")
        
        # Remove oldest turns if exceeding token budget
        while self.total_tokens > self.max_tokens and len(self._turns) > 1:
            removed = self._turns.pop(0)
            self._logger.debug(f"Evicted turn (token limit): {removed}")
    
    @property
    def total_tokens(self) -> int:
        """Estimate total tokens in memory."""
        return sum(turn.token_estimate for turn in self._turns)
    
    @property
    def turns(self) -> List[ConversationTurn]:
        """Get all turns (read-only copy)."""
        return self._turns.copy()
    
    def get_recent_turns(self, n: int = 5) -> List[ConversationTurn]:
        """Get the N most recent turns."""
        return self._turns[-n:] if n < len(self._turns) else self._turns.copy()
    
    def get_user_turns(self) -> List[ConversationTurn]:
        """Get only user turns."""
        return [t for t in self._turns if t.role == TurnRole.USER]
    
    def get_tool_turns(self) -> List[ConversationTurn]:
        """Get only tool execution turns."""
        return [t for t in self._turns if t.role == TurnRole.TOOL]
    
    def to_llm_messages(self) -> List[Dict]:
        """Convert memory to LLM message format."""
        return [turn.to_llm_message() for turn in self._turns]
    
    def get_context_string(self) -> str:
        """Get memory as a formatted string for context."""
        lines = []
        for turn in self._turns:
            role = turn.role.name.capitalize()
            lines.append(f"{role}: {turn.content}")
        return "\n".join(lines)
    
    def summarize(self) -> str:
        """
        Create a summary of the conversation.
        Used when memory needs to be compressed.
        """
        if not self._turns:
            return "No conversation history."
        
        user_turns = self.get_user_turns()
        tool_turns = self.get_tool_turns()
        
        summary_parts = []
        
        # Summarize user requests
        if user_turns:
            recent_requests = [t.content for t in user_turns[-3:]]
            summary_parts.append(f"Recent requests: {'; '.join(recent_requests)}")
        
        # Summarize tool usage
        if tool_turns:
            tools_used = list(set(t.tool_name for t in tool_turns if t.tool_name))
            summary_parts.append(f"Tools used: {', '.join(tools_used)}")
        
        return " | ".join(summary_parts)
    
    def clear(self) -> int:
        """Clear all memory. Returns number of turns cleared."""
        count = len(self._turns)
        self._turns = []
        self._logger.info(f"Cleared {count} turns from memory")
        return count
    
    def prune_before(self, timestamp: datetime) -> int:
        """Remove turns before a timestamp. Returns count removed."""
        original_count = len(self._turns)
        self._turns = [t for t in self._turns if t.timestamp >= timestamp]
        removed = original_count - len(self._turns)
        if removed:
            self._logger.info(f"Pruned {removed} turns before {timestamp}")
        return removed
    
    def __len__(self) -> int:
        return len(self._turns)
    
    def is_empty(self) -> bool:
        """Check if memory has no turns."""
        return len(self._turns) == 0


def test_memory() -> None:
    """Test conversation memory."""
    print("Testing Conversation Memory...")
    
    memory = ConversationMemory(max_turns=5, max_tokens=500)
    
    # Add some turns
    memory.add_user_turn("What time is it?")
    memory.add_assistant_turn("The current time is 10:30 AM.")
    memory.add_tool_turn("get_current_time", {}, "10:30 AM")
    memory.add_user_turn("Search for Python tutorials")
    memory.add_assistant_turn("I found several Python tutorials...")
    
    print(f"Turns: {len(memory)}")
    print(f"Tokens: ~{memory.total_tokens}")
    print(f"Summary: {memory.summarize()}")
    
    # Test eviction
    for i in range(5):
        memory.add_user_turn(f"Message {i}")
    
    print(f"\nAfter adding 5 more: {len(memory)} turns (max: 5)")
    
    # Test LLM format
    messages = memory.to_llm_messages()
    print(f"LLM messages: {len(messages)}")
    
    print("\nAll tests passed!")


if __name__ == "__main__":
    test_memory()
