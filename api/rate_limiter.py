"""
Rate Limiter
------------
Token bucket rate limiter for API calls.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Optional
import time


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""
    requests_per_minute: int = 60
    burst_size: int = 10  # Allow burst of requests


class RateLimiter:
    """
    Token bucket rate limiter.
    
    Thread-safe rate limiting for API calls.
    """
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()
        self._tokens = float(self.config.burst_size)
        self._last_update = datetime.now()
        self._lock = Lock()
        
        # Tokens per second
        self._rate = self.config.requests_per_minute / 60.0
    
    def acquire(self, timeout: float = 30.0) -> bool:
        """
        Acquire a token for making a request.
        Blocks until a token is available or timeout.
        
        Returns True if token acquired, False if timeout.
        """
        deadline = datetime.now() + timedelta(seconds=timeout)
        
        while datetime.now() < deadline:
            with self._lock:
                self._refill()
                
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
            
            # Wait a bit before retrying
            time.sleep(0.1)
        
        return False
    
    def try_acquire(self) -> bool:
        """
        Try to acquire a token without blocking.
        Returns True if token available, False otherwise.
        """
        with self._lock:
            self._refill()
            
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            
            return False
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = datetime.now()
        elapsed = (now - self._last_update).total_seconds()
        self._last_update = now
        
        # Add tokens based on elapsed time
        self._tokens = min(
            self.config.burst_size,
            self._tokens + (elapsed * self._rate)
        )
    
    @property
    def available_tokens(self) -> float:
        """Get current available tokens."""
        with self._lock:
            self._refill()
            return self._tokens
    
    def reset(self) -> None:
        """Reset the rate limiter."""
        with self._lock:
            self._tokens = float(self.config.burst_size)
            self._last_update = datetime.now()
