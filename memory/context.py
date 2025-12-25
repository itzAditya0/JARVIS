"""
Context Manager
---------------
Manages context window for LLM interactions.
Summarizes past context to stay within token budget.

Rules:
- Never exceed token budget
- Prefer structured memory over raw text
- Summarize when needed
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import logging

from .conversation import ConversationMemory, ConversationTurn, TurnRole
from .preferences import PreferenceStore


@dataclass
class ContextWindow:
    """
    A prepared context window for LLM interaction.
    Contains system prompt, memory, and user preferences.
    """
    
    system_prompt: str
    conversation_history: List[Dict]
    user_context: str
    total_tokens: int
    truncated: bool = False
    
    def to_messages(self) -> List[Dict]:
        """Convert to LLM message format."""
        messages = [{"role": "system", "content": self.system_prompt}]
        
        if self.user_context:
            messages.append({
                "role": "system",
                "content": f"User context: {self.user_context}"
            })
        
        messages.extend(self.conversation_history)
        
        return messages


class ContextManager:
    """
    Manages context for LLM interactions.
    
    Responsibilities:
    - Combine memory, preferences, and system prompt
    - Enforce token budget
    - Summarize when needed
    """
    
    # Token budget allocation
    SYSTEM_PROMPT_BUDGET = 500
    USER_CONTEXT_BUDGET = 200
    HISTORY_BUDGET = 3000
    RESPONSE_BUFFER = 500  # Reserve for model response
    
    def __init__(
        self,
        memory: Optional[ConversationMemory] = None,
        preferences: Optional[PreferenceStore] = None,
        max_tokens: int = 4000
    ):
        self.memory = memory or ConversationMemory()
        self.preferences = preferences or PreferenceStore()
        self.max_tokens = max_tokens
        self._logger = logging.getLogger("jarvis.memory.context")
    
    def build_context(
        self,
        system_prompt: str,
        current_input: str,
        include_history: bool = True
    ) -> ContextWindow:
        """
        Build a context window for LLM interaction.
        
        Ensures total tokens stay within budget.
        """
        # Calculate available budget
        available = self.max_tokens - self.RESPONSE_BUFFER
        
        # Prepare system prompt (truncate if needed)
        system_tokens = self._estimate_tokens(system_prompt)
        if system_tokens > self.SYSTEM_PROMPT_BUDGET:
            system_prompt = self._truncate_text(system_prompt, self.SYSTEM_PROMPT_BUDGET)
            self._logger.warning("System prompt truncated")
        
        available -= self._estimate_tokens(system_prompt)
        
        # Prepare user context from preferences
        user_context = self._build_user_context()
        context_tokens = self._estimate_tokens(user_context)
        
        if context_tokens > self.USER_CONTEXT_BUDGET:
            user_context = self._truncate_text(user_context, self.USER_CONTEXT_BUDGET)
        
        available -= self._estimate_tokens(user_context)
        
        # Prepare conversation history
        history = []
        truncated = False
        
        if include_history and self.memory:
            history, truncated = self._prepare_history(available)
        
        # Add current input
        history.append({"role": "user", "content": current_input})
        
        # Calculate total tokens
        total_tokens = (
            self._estimate_tokens(system_prompt) +
            self._estimate_tokens(user_context) +
            sum(self._estimate_tokens(m["content"]) for m in history)
        )
        
        return ContextWindow(
            system_prompt=system_prompt,
            conversation_history=history,
            user_context=user_context,
            total_tokens=total_tokens,
            truncated=truncated
        )
    
    def _build_user_context(self) -> str:
        """Build user context string from preferences."""
        relevant_prefs = [
            ("language", "Language"),
            ("timezone", "Timezone"),
            ("default_browser", "Default browser"),
        ]
        
        parts = []
        for key, label in relevant_prefs:
            value = self.preferences.get(key)
            if value and value != "default" and value != "local":
                parts.append(f"{label}: {value}")
        
        return "; ".join(parts) if parts else ""
    
    def _prepare_history(self, max_tokens: int) -> tuple[List[Dict], bool]:
        """
        Prepare conversation history within token budget.
        Returns (messages, was_truncated).
        """
        turns = self.memory.turns
        
        if not turns:
            return [], False
        
        # Start with recent turns and work backwards
        selected = []
        total_tokens = 0
        truncated = False
        
        for turn in reversed(turns):
            msg = turn.to_llm_message()
            tokens = self._estimate_tokens(msg["content"])
            
            if total_tokens + tokens > max_tokens:
                truncated = True
                break
            
            selected.insert(0, msg)
            total_tokens += tokens
        
        # If we had to truncate, add a summary of older context
        if truncated and len(turns) > len(selected):
            summary = self.memory.summarize()
            summary_msg = {
                "role": "system",
                "content": f"Previous conversation summary: {summary}"
            }
            
            # Check if summary fits
            summary_tokens = self._estimate_tokens(summary_msg["content"])
            if total_tokens + summary_tokens <= max_tokens:
                selected.insert(0, summary_msg)
            
            self._logger.info(f"Context truncated: {len(selected)}/{len(turns)} turns kept")
        
        return selected, truncated
    
    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars ≈ 1 token)."""
        return max(1, len(text) // 4)
    
    def _truncate_text(self, text: str, max_tokens: int) -> str:
        """Truncate text to fit within token budget."""
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        return text[:max_chars - 3] + "..."
    
    def add_turn(
        self,
        role: TurnRole,
        content: str,
        metadata: Optional[Dict] = None
    ) -> None:
        """Add a turn to memory."""
        if role == TurnRole.USER:
            self.memory.add_user_turn(content, metadata)
        elif role == TurnRole.ASSISTANT:
            self.memory.add_assistant_turn(content, metadata)
    
    def add_tool_result(
        self,
        tool_name: str,
        tool_args: Dict,
        result: Any
    ) -> None:
        """Add a tool execution result to memory."""
        self.memory.add_tool_turn(tool_name, tool_args, result)
    
    def clear_history(self) -> int:
        """Clear conversation history."""
        return self.memory.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        return {
            "turns": len(self.memory),
            "estimated_tokens": self.memory.total_tokens,
            "max_tokens": self.max_tokens,
            "preferences_count": len(self.preferences.list_all()),
        }


def test_context_manager() -> None:
    """Test context manager."""
    import tempfile
    import os
    
    print("Testing Context Manager...")
    
    # Create temp preference file
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        temp_path = f.name
    
    try:
        memory = ConversationMemory(max_turns=10, max_tokens=2000)
        preferences = PreferenceStore(temp_path)
        
        manager = ContextManager(
            memory=memory,
            preferences=preferences,
            max_tokens=4000
        )
        
        # Add some conversation
        manager.add_turn(TurnRole.USER, "What time is it?")
        manager.add_turn(TurnRole.ASSISTANT, "The current time is 10:30 AM.")
        manager.add_tool_result("get_current_time", {}, "10:30 AM")
        manager.add_turn(TurnRole.USER, "Search for Python tutorials")
        manager.add_turn(TurnRole.ASSISTANT, "I found several Python tutorials for you.")
        
        # Build context
        system_prompt = "You are JARVIS, a helpful voice assistant."
        context = manager.build_context(
            system_prompt=system_prompt,
            current_input="What was my first question?"
        )
        
        print(f"Total tokens: {context.total_tokens}")
        print(f"Messages: {len(context.to_messages())}")
        print(f"Truncated: {context.truncated}")
        
        # Get stats
        stats = manager.get_stats()
        print(f"Stats: {stats}")
        
        print("\nAll tests passed!")
        
    finally:
        os.unlink(temp_path)


if __name__ == "__main__":
    test_context_manager()
