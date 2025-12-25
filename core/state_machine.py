"""
State Machine
-------------
Manages system state transitions with validation.
All state transitions are logged and auditable.

Exit Criterion: You can log every state transition.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Callable, Dict, List, Optional, Set
import logging


class State(Enum):
    """Valid states for the JARVIS system."""
    IDLE = auto()          # Waiting for user input
    LISTENING = auto()     # Capturing audio
    TRANSCRIBING = auto()  # Converting speech to text
    PLANNING = auto()      # Matching command (Phase 1) / LLM planning (Phase 2)
    EXECUTING = auto()     # Running command
    RESPONDING = auto()    # Outputting result
    ERROR = auto()         # Error state


@dataclass
class StateTransition:
    """Record of a state transition."""
    from_state: State
    to_state: State
    timestamp: datetime
    reason: str
    metadata: Dict = field(default_factory=dict)
    
    def __repr__(self) -> str:
        return (
            f"StateTransition({self.from_state.name} → {self.to_state.name}, "
            f"reason='{self.reason}')"
        )


# Define valid state transitions
VALID_TRANSITIONS: Dict[State, Set[State]] = {
    State.IDLE: {State.LISTENING, State.PLANNING, State.ERROR},  # PLANNING for text input bypass
    State.LISTENING: {State.IDLE, State.TRANSCRIBING, State.ERROR},
    State.TRANSCRIBING: {State.PLANNING, State.IDLE, State.ERROR},
    State.PLANNING: {State.EXECUTING, State.RESPONDING, State.IDLE, State.ERROR},
    State.EXECUTING: {State.RESPONDING, State.ERROR},
    State.RESPONDING: {State.IDLE, State.LISTENING, State.ERROR},
    State.ERROR: {State.IDLE},  # Can only recover to IDLE
}


class StateMachine:
    """
    State machine for JARVIS system.
    
    Responsibilities:
    - Track current state
    - Validate state transitions
    - Log all transitions
    - Notify listeners of state changes
    """
    
    def __init__(self, initial_state: State = State.IDLE):
        self._state = initial_state
        self._history: List[StateTransition] = []
        self._listeners: List[Callable[[StateTransition], None]] = []
        self._logger = logging.getLogger("jarvis.state")
        
        # Log initial state
        self._logger.info(f"State machine initialized in state: {self._state.name}")
    
    @property
    def state(self) -> State:
        """Get current state."""
        return self._state
    
    @property
    def history(self) -> List[StateTransition]:
        """Get transition history."""
        return self._history.copy()
    
    def can_transition(self, to_state: State) -> bool:
        """Check if transition to given state is valid."""
        valid = VALID_TRANSITIONS.get(self._state, set())
        return to_state in valid
    
    def transition(
        self,
        to_state: State,
        reason: str,
        metadata: Optional[Dict] = None
    ) -> StateTransition:
        """
        Transition to a new state.
        
        Args:
            to_state: Target state
            reason: Human-readable reason for transition
            metadata: Optional additional data
        
        Returns:
            StateTransition record
        
        Raises:
            ValueError: If transition is not valid
        """
        if not self.can_transition(to_state):
            valid = VALID_TRANSITIONS.get(self._state, set())
            valid_names = [s.name for s in valid]
            raise ValueError(
                f"Invalid transition: {self._state.name} → {to_state.name}. "
                f"Valid targets: {valid_names}"
            )
        
        # Create transition record
        transition = StateTransition(
            from_state=self._state,
            to_state=to_state,
            timestamp=datetime.now(),
            reason=reason,
            metadata=metadata or {}
        )
        
        # Update state
        old_state = self._state
        self._state = to_state
        
        # Record in history
        self._history.append(transition)
        
        # Log transition
        self._logger.info(
            f"State transition: {old_state.name} → {to_state.name} "
            f"(reason: {reason})"
        )
        
        # Notify listeners
        for listener in self._listeners:
            try:
                listener(transition)
            except Exception as e:
                self._logger.warning(f"Listener error: {e}")
        
        return transition
    
    def add_listener(
        self,
        callback: Callable[[StateTransition], None]
    ) -> None:
        """Add a state change listener."""
        self._listeners.append(callback)
    
    def remove_listener(
        self,
        callback: Callable[[StateTransition], None]
    ) -> None:
        """Remove a state change listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)
    
    def reset(self, reason: str = "Manual reset") -> None:
        """Reset to IDLE state."""
        if self._state != State.IDLE:
            # Force transition to ERROR then IDLE if needed
            if self._state != State.ERROR:
                self._state = State.ERROR
                self._history.append(StateTransition(
                    from_state=self._state,
                    to_state=State.ERROR,
                    timestamp=datetime.now(),
                    reason=f"Reset initiated: {reason}"
                ))
            
            self.transition(State.IDLE, reason)
    
    def is_busy(self) -> bool:
        """Check if system is in a busy state."""
        return self._state not in {State.IDLE, State.ERROR}
    
    def get_history_summary(self) -> str:
        """Get a human-readable summary of recent transitions."""
        if not self._history:
            return "No transitions recorded."
        
        lines = ["State Transition History:", "-" * 40]
        
        for t in self._history[-10:]:  # Last 10 transitions
            lines.append(
                f"  {t.timestamp.strftime('%H:%M:%S')} | "
                f"{t.from_state.name:12} → {t.to_state.name:12} | "
                f"{t.reason}"
            )
        
        return "\n".join(lines)


def test_state_machine() -> None:
    """Test the state machine standalone."""
    print("Testing State Machine...")
    
    sm = StateMachine()
    
    # Track transitions
    transitions = []
    sm.add_listener(lambda t: transitions.append(t))
    
    # Simulate a command flow
    try:
        sm.transition(State.LISTENING, "User pressed push-to-talk")
        sm.transition(State.TRANSCRIBING, "Audio captured")
        sm.transition(State.PLANNING, "Transcription complete")
        sm.transition(State.EXECUTING, "Command matched")
        sm.transition(State.RESPONDING, "Execution complete")
        sm.transition(State.IDLE, "Response delivered")
        
        print("\n✓ Valid transition sequence completed")
        print(f"  Total transitions: {len(transitions)}")
        print(f"\n{sm.get_history_summary()}")
        
    except ValueError as e:
        print(f"✗ Error: {e}")
    
    # Test invalid transition
    print("\nTesting invalid transition...")
    sm.reset()
    
    try:
        sm.transition(State.EXECUTING, "Should fail")
        print("✗ Should have raised ValueError")
    except ValueError as e:
        print(f"✓ Correctly rejected: {e}")


if __name__ == "__main__":
    test_state_machine()
