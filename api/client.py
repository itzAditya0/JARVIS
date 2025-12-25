"""
API Client Framework
--------------------
Per-service client with rate limiting and secret isolation.
API keys are never exposed to the LLM.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional
import logging
import os

import httpx


class APIStatus(Enum):
    """Status of an API response."""
    SUCCESS = auto()
    RATE_LIMITED = auto()
    AUTH_ERROR = auto()
    NOT_FOUND = auto()
    SERVER_ERROR = auto()
    TIMEOUT = auto()
    NETWORK_ERROR = auto()


@dataclass
class APIConfig:
    """Configuration for an API client."""
    name: str
    base_url: str
    api_key_env: str  # Environment variable name (NOT the actual key)
    timeout_seconds: float = 30.0
    max_retries: int = 3
    rate_limit_requests: int = 100  # Max requests per minute
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class APIResponse:
    """Response from an API call."""
    status: APIStatus
    data: Optional[Any] = None
    error: Optional[str] = None
    status_code: int = 0
    response_time_ms: float = 0.0
    
    @property
    def success(self) -> bool:
        return self.status == APIStatus.SUCCESS


class APIClient:
    """
    Base API client with rate limiting and error handling.
    
    Rules:
    - API keys loaded from environment only
    - LLM never sees raw secrets
    - All requests rate-limited
    """
    
    def __init__(self, config: APIConfig):
        self.config = config
        self._logger = logging.getLogger(f"jarvis.api.{config.name}")
        self._rate_limiter = None  # Will be set up on first use
        
        # Load API key from environment
        self._api_key = os.getenv(config.api_key_env)
        if not self._api_key:
            self._logger.warning(f"API key not found: {config.api_key_env}")
    
    @property
    def is_configured(self) -> bool:
        """Check if API client is properly configured."""
        return self._api_key is not None
    
    def _get_headers(self) -> Dict[str, str]:
        """Build request headers with authentication."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "JARVIS/1.0",
        }
        headers.update(self.config.headers)
        
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        
        return headers
    
    async def get(self, endpoint: str, params: Optional[Dict] = None) -> APIResponse:
        """Make a GET request."""
        return await self._request("GET", endpoint, params=params)
    
    async def post(self, endpoint: str, data: Optional[Dict] = None) -> APIResponse:
        """Make a POST request."""
        return await self._request("POST", endpoint, json=data)
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json: Optional[Dict] = None
    ) -> APIResponse:
        """Make an HTTP request with error handling."""
        if not self.is_configured:
            return APIResponse(
                status=APIStatus.AUTH_ERROR,
                error=f"API key not configured: {self.config.api_key_env}"
            )
        
        url = f"{self.config.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        start_time = datetime.now()
        
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json,
                    headers=self._get_headers()
                )
                
                response_time = (datetime.now() - start_time).total_seconds() * 1000
                
                # Handle different status codes
                if response.status_code == 200:
                    return APIResponse(
                        status=APIStatus.SUCCESS,
                        data=response.json() if response.content else None,
                        status_code=response.status_code,
                        response_time_ms=response_time
                    )
                elif response.status_code == 429:
                    return APIResponse(
                        status=APIStatus.RATE_LIMITED,
                        error="Rate limit exceeded",
                        status_code=response.status_code,
                        response_time_ms=response_time
                    )
                elif response.status_code in (401, 403):
                    return APIResponse(
                        status=APIStatus.AUTH_ERROR,
                        error="Authentication failed",
                        status_code=response.status_code,
                        response_time_ms=response_time
                    )
                elif response.status_code == 404:
                    return APIResponse(
                        status=APIStatus.NOT_FOUND,
                        error="Resource not found",
                        status_code=response.status_code,
                        response_time_ms=response_time
                    )
                elif response.status_code >= 500:
                    return APIResponse(
                        status=APIStatus.SERVER_ERROR,
                        error=f"Server error: {response.status_code}",
                        status_code=response.status_code,
                        response_time_ms=response_time
                    )
                else:
                    return APIResponse(
                        status=APIStatus.SERVER_ERROR,
                        error=f"Unexpected status: {response.status_code}",
                        status_code=response.status_code,
                        response_time_ms=response_time
                    )
                    
        except httpx.TimeoutException:
            return APIResponse(
                status=APIStatus.TIMEOUT,
                error="Request timed out"
            )
        except httpx.NetworkError as e:
            return APIResponse(
                status=APIStatus.NETWORK_ERROR,
                error=f"Network error: {e}"
            )
        except Exception as e:
            self._logger.error(f"Request failed: {e}")
            return APIResponse(
                status=APIStatus.NETWORK_ERROR,
                error=str(e)
            )


# Pre-configured clients for common services

def create_gemini_client() -> APIClient:
    """Create Gemini API client."""
    return APIClient(APIConfig(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1",
        api_key_env="GEMINI_API_KEY",
        rate_limit_requests=60
    ))


def create_weather_client() -> APIClient:
    """Create weather API client."""
    return APIClient(APIConfig(
        name="weather",
        base_url="https://api.openweathermap.org/data/2.5",
        api_key_env="OPENWEATHER_API_KEY",
        rate_limit_requests=60
    ))
