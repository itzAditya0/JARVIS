"""
Event-Driven Triggers
---------------------
Time-based and event-driven automation triggers.
All triggers are explicitly configured - no autonomous actions.

Rules:
- No autonomous event loops
- All triggers explicitly configured by user
- Easy to audit and disable
- Clear execution logging
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Union
import asyncio
import json
import logging
import threading
from pathlib import Path
import sched
import time


class TriggerType(Enum):
    """Types of triggers."""
    TIME = auto()        # Execute at specific time
    INTERVAL = auto()    # Execute every N seconds/minutes
    CRON = auto()        # Cron-like schedule (future)
    FILE_WATCH = auto()  # Watch for file changes (future)
    MANUAL = auto()      # Manual trigger only


class TriggerState(Enum):
    """State of a trigger."""
    ACTIVE = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class TimeSpec:
    """Time specification for triggers."""
    hour: Optional[int] = None      # 0-23
    minute: Optional[int] = None    # 0-59
    second: int = 0                 # 0-59
    weekday: Optional[int] = None   # 0=Monday, 6=Sunday
    
    def matches(self, dt: datetime) -> bool:
        """Check if datetime matches this spec."""
        if self.hour is not None and dt.hour != self.hour:
            return False
        if self.minute is not None and dt.minute != self.minute:
            return False
        if self.weekday is not None and dt.weekday() != self.weekday:
            return False
        return True
    
    def next_occurrence(self, after: Optional[datetime] = None) -> datetime:
        """Calculate the next occurrence after the given time."""
        now = after or datetime.now()
        
        # Start from now
        target = now.replace(second=self.second, microsecond=0)
        
        if self.minute is not None:
            target = target.replace(minute=self.minute)
        if self.hour is not None:
            target = target.replace(hour=self.hour)
        
        # If target is in the past, move to next occurrence
        if target <= now:
            if self.minute is None:
                target += timedelta(hours=1)
            elif self.hour is None:
                target += timedelta(days=1)
            else:
                target += timedelta(days=1)
        
        return target


@dataclass
class ScheduledTask:
    """A scheduled task."""
    id: str
    name: str
    action: str  # Command text to execute
    trigger_type: TriggerType
    
    # Schedule configuration
    time_spec: Optional[TimeSpec] = None
    interval_seconds: Optional[int] = None
    
    # State
    state: TriggerState = TriggerState.ACTIVE
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    max_runs: Optional[int] = None  # None = unlimited
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "action": self.action,
            "trigger_type": self.trigger_type.name,
            "state": self.state.name,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "run_count": self.run_count,
            "description": self.description
        }


@dataclass
class EventTrigger:
    """An event that can trigger actions."""
    name: str
    event_type: str
    conditions: Dict[str, Any] = field(default_factory=dict)
    action: str = ""
    enabled: bool = True
    
    def matches(self, event_data: Dict[str, Any]) -> bool:
        """Check if event data matches trigger conditions."""
        if not self.enabled:
            return False
        
        for key, expected in self.conditions.items():
            if key not in event_data:
                return False
            if event_data[key] != expected:
                return False
        
        return True


class EventManager:
    """
    Manages scheduled tasks and event triggers.
    
    All automation is:
    - Explicitly configured
    - Easy to audit
    - Easy to disable
    """
    
    def __init__(self, orchestrator=None, persist_file: Optional[str] = None):
        self._orchestrator = orchestrator
        self._persist_file = Path(persist_file) if persist_file else None
        self._tasks: Dict[str, ScheduledTask] = {}
        self._triggers: Dict[str, EventTrigger] = {}
        self._logger = logging.getLogger("jarvis.multimodal.events")
        
        self._scheduler = sched.scheduler(time.time, time.sleep)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # Load persisted tasks
        if self._persist_file and self._persist_file.exists():
            self._load_tasks()
    
    def set_orchestrator(self, orchestrator) -> None:
        """Set the orchestrator for executing actions."""
        self._orchestrator = orchestrator
    
    # Task Management
    
    def add_task(self, task: ScheduledTask) -> None:
        """Add a scheduled task."""
        self._tasks[task.id] = task
        self._calculate_next_run(task)
        self._logger.info(f"Task added: {task.name} ({task.id})")
        self._persist_tasks()
    
    def remove_task(self, task_id: str) -> bool:
        """Remove a scheduled task."""
        if task_id in self._tasks:
            del self._tasks[task_id]
            self._logger.info(f"Task removed: {task_id}")
            self._persist_tasks()
            return True
        return False
    
    def pause_task(self, task_id: str) -> bool:
        """Pause a task."""
        if task_id in self._tasks:
            self._tasks[task_id].state = TriggerState.PAUSED
            self._logger.info(f"Task paused: {task_id}")
            return True
        return False
    
    def resume_task(self, task_id: str) -> bool:
        """Resume a paused task."""
        if task_id in self._tasks:
            task = self._tasks[task_id]
            task.state = TriggerState.ACTIVE
            self._calculate_next_run(task)
            self._logger.info(f"Task resumed: {task_id}")
            return True
        return False
    
    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Get a task by ID."""
        return self._tasks.get(task_id)
    
    def list_tasks(self) -> List[ScheduledTask]:
        """List all tasks."""
        return list(self._tasks.values())
    
    # Trigger Management
    
    def add_trigger(self, trigger: EventTrigger) -> None:
        """Add an event trigger."""
        self._triggers[trigger.name] = trigger
        self._logger.info(f"Trigger added: {trigger.name}")
    
    def remove_trigger(self, name: str) -> bool:
        """Remove a trigger."""
        if name in self._triggers:
            del self._triggers[name]
            return True
        return False
    
    def fire_event(self, event_type: str, event_data: Dict[str, Any]) -> List[str]:
        """
        Fire an event and execute matching triggers.
        Returns list of triggered action IDs.
        """
        triggered = []
        
        for trigger in self._triggers.values():
            if trigger.event_type == event_type and trigger.matches(event_data):
                self._logger.info(f"Event triggered: {trigger.name}")
                self._execute_action(trigger.action)
                triggered.append(trigger.name)
        
        return triggered
    
    # Execution
    
    def _calculate_next_run(self, task: ScheduledTask) -> None:
        """Calculate next run time for a task."""
        if task.state != TriggerState.ACTIVE:
            task.next_run = None
            return
        
        now = datetime.now()
        
        if task.trigger_type == TriggerType.TIME and task.time_spec:
            task.next_run = task.time_spec.next_occurrence(now)
        
        elif task.trigger_type == TriggerType.INTERVAL and task.interval_seconds:
            if task.last_run:
                task.next_run = task.last_run + timedelta(seconds=task.interval_seconds)
                if task.next_run <= now:
                    task.next_run = now + timedelta(seconds=task.interval_seconds)
            else:
                task.next_run = now + timedelta(seconds=task.interval_seconds)
    
    def _execute_action(self, action: str) -> Optional[str]:
        """Execute an action (command text)."""
        if not self._orchestrator:
            self._logger.warning("No orchestrator configured, cannot execute action")
            return None
        
        self._logger.info(f"Executing action: {action}")
        
        try:
            result = self._orchestrator.process_text_directly(action)
            return result
        except Exception as e:
            self._logger.error(f"Action execution error: {e}")
            return None
    
    def _run_task(self, task_id: str) -> None:
        """Run a scheduled task."""
        task = self._tasks.get(task_id)
        if not task or task.state != TriggerState.ACTIVE:
            return
        
        self._logger.info(f"Running task: {task.name}")
        
        # Execute the action
        self._execute_action(task.action)
        
        # Update task state
        task.last_run = datetime.now()
        task.run_count += 1
        
        # Check if max runs reached
        if task.max_runs and task.run_count >= task.max_runs:
            task.state = TriggerState.COMPLETED
            self._logger.info(f"Task completed (max runs): {task.name}")
        else:
            # Schedule next run
            self._calculate_next_run(task)
        
        self._persist_tasks()
    
    # Scheduler Loop
    
    def start(self) -> None:
        """Start the event manager scheduler."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        self._logger.info("Event manager started")
    
    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self._logger.info("Event manager stopped")
    
    def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            now = datetime.now()
            
            # Check all active tasks
            for task in self._tasks.values():
                if task.state != TriggerState.ACTIVE:
                    continue
                
                if task.next_run and task.next_run <= now:
                    self._run_task(task.id)
            
            # Sleep briefly
            time.sleep(1)
    
    # Persistence - DISABLED in v0.5.1 (SQLite is single source of truth)
    
    def _persist_tasks(self) -> None:
        """Save tasks to file - DISABLED.
        
        v0.5.1: JSON persistence removed. Use DatabaseManager instead.
        """
        if self._persist_file:
            raise RuntimeError(
                "JSON persistence is disabled in v0.5.1+. "
                "Use infra.database.DatabaseManager for task persistence."
            )
    
    def _load_tasks(self) -> None:
        """Load tasks from file - DISABLED.
        
        v0.5.1: JSON persistence removed. Use DatabaseManager instead.
        """
        if self._persist_file and self._persist_file.exists():
            self._logger.warning(
                f"Legacy JSON task file found at {self._persist_file}. "
                f"JSON persistence is disabled. Migrate to DatabaseManager."
            )
            # Do not load - fail safe

    
    # Convenience Methods
    
    def schedule_at(
        self,
        name: str,
        action: str,
        hour: int,
        minute: int = 0,
        description: str = ""
    ) -> ScheduledTask:
        """Schedule a task for a specific time daily."""
        import uuid
        
        task = ScheduledTask(
            id=str(uuid.uuid4())[:8],
            name=name,
            action=action,
            trigger_type=TriggerType.TIME,
            time_spec=TimeSpec(hour=hour, minute=minute),
            description=description
        )
        
        self.add_task(task)
        return task
    
    def schedule_interval(
        self,
        name: str,
        action: str,
        interval_seconds: int,
        max_runs: Optional[int] = None,
        description: str = ""
    ) -> ScheduledTask:
        """Schedule a task to run at regular intervals."""
        import uuid
        
        task = ScheduledTask(
            id=str(uuid.uuid4())[:8],
            name=name,
            action=action,
            trigger_type=TriggerType.INTERVAL,
            interval_seconds=interval_seconds,
            max_runs=max_runs,
            description=description
        )
        
        self.add_task(task)
        return task


def test_events() -> None:
    """Test event management."""
    print("Testing Event Manager...")
    
    manager = EventManager()
    
    # Test interval scheduling
    print("\nScheduling interval task (runs every 2 seconds, max 3 times)...")
    task = manager.schedule_interval(
        name="Test Task",
        action="what time is it",
        interval_seconds=2,
        max_runs=3
    )
    
    print(f"Task created: {task.id}")
    print(f"Next run: {task.next_run}")
    
    # Test time scheduling
    print("\nScheduling time-based task...")
    now = datetime.now()
    future_task = manager.schedule_at(
        name="Future Task",
        action="check system status",
        hour=(now.hour + 1) % 24,
        minute=0
    )
    
    print(f"Future task next run: {future_task.next_run}")
    
    # List tasks
    print(f"\nTotal tasks: {len(manager.list_tasks())}")
    for t in manager.list_tasks():
        print(f"  - {t.name}: {t.state.name}")
    
    # Test trigger
    print("\nTesting event trigger...")
    trigger = EventTrigger(
        name="test_trigger",
        event_type="user_command",
        conditions={"type": "greeting"},
        action="hello there"
    )
    manager.add_trigger(trigger)
    
    # Fire event
    triggered = manager.fire_event("user_command", {"type": "greeting"})
    print(f"Triggered: {triggered}")
    
    print("\nAll tests complete!")


if __name__ == "__main__":
    test_events()
