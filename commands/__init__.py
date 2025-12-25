# Commands module - Command registry and matching
# This module does NOT execute commands, only matches them
# No OS execution, no LLM logic

from .registry import CommandRegistry, CommandIntent, CommandDefinition

__all__ = ["CommandRegistry", "CommandIntent", "CommandDefinition"]
