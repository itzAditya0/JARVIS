"""
Health Monitoring
------------------
Component health tracking for observability.

v0.8.0: Reliability release.

Design:
- Passive observability only (no auto-actions)
- Per-component health status
- Error rate and latency tracking
- Integration with circuit breakers
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum, auto
from typing import Any, Dict, List, Optional
import logging
import threading
import time


class HealthStatus(Enum):
    """Component health status."""
    HEALTHY = auto()     # Normal operation
    DEGRADED = auto()    # Functioning with issues
    UNHEALTHY = auto()   # Not functioning properly


@dataclass
class ComponentHealth:
    """
    Health status of a single component.
    
    Tracks:
    - Current status
    - Error rate
    - Latency statistics
    - Recent errors
    """
    name: str
    status: HealthStatus = HealthStatus.HEALTHY
    last_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_calls: int = 0
    total_errors: int = 0
    total_latency_ms: float = 0.0
    _recent_latencies: List[float] = field(default_factory=list, repr=False)
    _max_recent: int = field(default=100, repr=False)
    
    @property
    def error_rate(self) -> float:
        """Calculate error rate (0.0 - 1.0)."""
        if self.total_calls == 0:
            return 0.0
        return self.total_errors / self.total_calls
    
    @property
    def avg_latency_ms(self) -> float:
        """Calculate average latency."""
        if self.total_calls == 0:
            return 0.0
        return self.total_latency_ms / self.total_calls
    
    @property
    def latency_p99_ms(self) -> float:
        """Calculate p99 latency from recent samples."""
        if not self._recent_latencies:
            return 0.0
        sorted_latencies = sorted(self._recent_latencies)
        idx = int(len(sorted_latencies) * 0.99)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]
    
    def record_call(self, latency_ms: float, is_error: bool = False) -> None:
        """Record a call to this component."""
        self.total_calls += 1
        self.total_latency_ms += latency_ms
        self.last_check = datetime.now(timezone.utc)
        
        # Track recent latencies for percentiles
        self._recent_latencies.append(latency_ms)
        if len(self._recent_latencies) > self._max_recent:
            self._recent_latencies.pop(0)
        
        if is_error:
            self.total_errors += 1
        
        # Update status based on error rate
        self._update_status()
    
    def _update_status(self) -> None:
        """Update health status based on metrics."""
        error_rate = self.error_rate
        
        if error_rate >= 0.5:
            self.status = HealthStatus.UNHEALTHY
        elif error_rate >= 0.1:
            self.status = HealthStatus.DEGRADED
        else:
            self.status = HealthStatus.HEALTHY
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API/logging."""
        return {
            "name": self.name,
            "status": self.status.name,
            "last_check": self.last_check.isoformat(),
            "total_calls": self.total_calls,
            "total_errors": self.total_errors,
            "error_rate": round(self.error_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "latency_p99_ms": round(self.latency_p99_ms, 2),
        }


class HealthMonitor:
    """
    Central health monitoring for all components.
    
    Design:
    - Passive observability only
    - Does NOT auto-disable or auto-switch
    - Provides data for human/external decisions
    """
    
    def __init__(self):
        self._components: Dict[str, ComponentHealth] = {}
        self._lock = threading.Lock()
        self._logger = logging.getLogger("jarvis.health")
    
    def get_or_create(self, name: str) -> ComponentHealth:
        """Get or create health tracker for component."""
        with self._lock:
            if name not in self._components:
                self._components[name] = ComponentHealth(name=name)
            return self._components[name]
    
    def record_call(
        self,
        component: str,
        latency_ms: float,
        is_error: bool = False
    ) -> None:
        """Record a call to a component."""
        health = self.get_or_create(component)
        health.record_call(latency_ms, is_error)
        
        # Log status changes
        if is_error and health.status != HealthStatus.HEALTHY:
            self._logger.warning(
                f"Component {component} is {health.status.name} "
                f"(error_rate={health.error_rate:.2%})"
            )
    
    def check_all(self) -> Dict[str, ComponentHealth]:
        """Get health of all registered components."""
        with self._lock:
            return dict(self._components)
    
    def is_healthy(self) -> bool:
        """Check if ALL components are healthy."""
        with self._lock:
            return all(
                c.status == HealthStatus.HEALTHY
                for c in self._components.values()
            )
    
    def get_degraded(self) -> List[str]:
        """Get list of degraded component names."""
        with self._lock:
            return [
                name for name, health in self._components.items()
                if health.status == HealthStatus.DEGRADED
            ]
    
    def get_unhealthy(self) -> List[str]:
        """Get list of unhealthy component names."""
        with self._lock:
            return [
                name for name, health in self._components.items()
                if health.status == HealthStatus.UNHEALTHY
            ]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get overall health summary."""
        with self._lock:
            healthy = sum(1 for c in self._components.values() if c.status == HealthStatus.HEALTHY)
            degraded = sum(1 for c in self._components.values() if c.status == HealthStatus.DEGRADED)
            unhealthy = sum(1 for c in self._components.values() if c.status == HealthStatus.UNHEALTHY)
            
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_components": len(self._components),
                "healthy": healthy,
                "degraded": degraded,
                "unhealthy": unhealthy,
                "overall_status": self._get_overall_status().name,
                "components": {
                    name: health.to_dict()
                    for name, health in self._components.items()
                }
            }
    
    def _get_overall_status(self) -> HealthStatus:
        """Derive overall system health."""
        if not self._components:
            return HealthStatus.HEALTHY
        
        statuses = [c.status for c in self._components.values()]
        
        if any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY
        if any(s == HealthStatus.DEGRADED for s in statuses):
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY
    
    def reset(self, component: Optional[str] = None) -> None:
        """Reset health stats (optionally for specific component)."""
        with self._lock:
            if component:
                if component in self._components:
                    self._components[component] = ComponentHealth(name=component)
            else:
                self._components.clear()


# Global monitor instance
_default_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    """Get or create the default health monitor."""
    global _default_monitor
    if _default_monitor is None:
        _default_monitor = HealthMonitor()
    return _default_monitor
