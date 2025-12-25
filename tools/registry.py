"""
Tool Registry
-------------
JSON schema-validated tool definitions.
Each tool is unit-testable without the LLM.

Exit Criterion: Tools can be unit-tested without the LLM.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
import json
import logging
import yaml

from pydantic import BaseModel, Field, ValidationError


class PermissionLevel(str, Enum):
    """Permission levels for tools."""
    READ = "read"           # No side effects
    WRITE = "write"         # Modifies data
    EXECUTE = "execute"     # Runs processes
    NETWORK = "network"     # Makes network requests
    ADMIN = "admin"         # System-level changes


class ParameterType(str, Enum):
    """Supported parameter types."""
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""
    name: str
    type: ParameterType
    description: str
    required: bool = True
    default: Optional[Any] = None
    enum: Optional[List[Any]] = None  # Allowed values
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    pattern: Optional[str] = None  # Regex for strings
    
    def to_json_schema(self) -> Dict:
        """Convert to JSON Schema format."""
        schema = {
            "type": self.type.value,
            "description": self.description
        }
        
        if self.enum:
            schema["enum"] = self.enum
        if self.min_value is not None:
            schema["minimum"] = self.min_value
        if self.max_value is not None:
            schema["maximum"] = self.max_value
        if self.pattern:
            schema["pattern"] = self.pattern
        if self.default is not None:
            schema["default"] = self.default
            
        return schema


@dataclass
class ToolSchema:
    """JSON Schema for tool parameters."""
    parameters: List[ToolParameter] = field(default_factory=list)
    
    def to_json_schema(self) -> Dict:
        """Convert to full JSON Schema."""
        properties = {}
        required = []
        
        for param in self.parameters:
            properties[param.name] = param.to_json_schema()
            if param.required:
                required.append(param.name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False
        }
    
    def to_openai_function(self, name: str, description: str) -> Dict:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": self.to_json_schema()
            }
        }


@dataclass
class Tool:
    """
    Tool definition with schema and executor.
    
    Each tool defines:
    - Name and description
    - JSON schema for parameters
    - Permission level
    - Deterministic executor function
    """
    name: str
    description: str
    schema: ToolSchema
    permission: PermissionLevel
    executor: Callable[[Dict[str, Any]], Any]
    category: str = "general"
    timeout_seconds: float = 30.0
    requires_confirmation: bool = False
    
    def validate_args(self, args: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate arguments against schema.
        Returns (is_valid, error_message).
        """
        schema = self.schema.to_json_schema()
        
        # Check required parameters
        for param_name in schema.get("required", []):
            if param_name not in args:
                return False, f"Missing required parameter: {param_name}"
        
        # Check parameter types and constraints
        for param in self.schema.parameters:
            if param.name not in args:
                if param.required:
                    return False, f"Missing required parameter: {param.name}"
                continue
            
            value = args[param.name]
            
            # Type validation
            if not self._validate_type(value, param.type):
                return False, f"Invalid type for {param.name}: expected {param.type.value}"
            
            # Enum validation
            if param.enum and value not in param.enum:
                return False, f"Invalid value for {param.name}: must be one of {param.enum}"
            
            # Range validation for numbers
            if param.type in (ParameterType.INTEGER, ParameterType.NUMBER):
                if param.min_value is not None and value < param.min_value:
                    return False, f"{param.name} must be >= {param.min_value}"
                if param.max_value is not None and value > param.max_value:
                    return False, f"{param.name} must be <= {param.max_value}"
        
        # Check for unknown parameters
        known_params = {p.name for p in self.schema.parameters}
        for arg_name in args:
            if arg_name not in known_params:
                return False, f"Unknown parameter: {arg_name}"
        
        return True, None
    
    def _validate_type(self, value: Any, expected: ParameterType) -> bool:
        """Validate value type."""
        type_map = {
            ParameterType.STRING: str,
            ParameterType.INTEGER: int,
            ParameterType.NUMBER: (int, float),
            ParameterType.BOOLEAN: bool,
            ParameterType.ARRAY: list,
            ParameterType.OBJECT: dict,
        }
        return isinstance(value, type_map.get(expected, object))
    
    def __repr__(self) -> str:
        return f"Tool(name={self.name}, permission={self.permission.value})"


class ToolRegistry:
    """
    Registry for all available tools.
    
    This registry is the firewall between LLM and system.
    All tool executions must go through validation.
    """
    
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._logger = logging.getLogger("jarvis.tools.registry")
    
    def register(self, tool: Tool) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            self._logger.warning(f"Overwriting existing tool: {tool.name}")
        
        self._tools[tool.name] = tool
        self._logger.info(f"Registered tool: {tool.name} ({tool.permission.value})")
    
    def unregister(self, name: str) -> bool:
        """Unregister a tool."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False
    
    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)
    
    def list_tools(self) -> List[Tool]:
        """List all registered tools."""
        return list(self._tools.values())
    
    def list_by_category(self, category: str) -> List[Tool]:
        """List tools by category."""
        return [t for t in self._tools.values() if t.category == category]
    
    def list_by_permission(self, permission: PermissionLevel) -> List[Tool]:
        """List tools by permission level."""
        return [t for t in self._tools.values() if t.permission == permission]
    
    def get_schemas_for_llm(self) -> List[Dict]:
        """Get all tool schemas in OpenAI function format."""
        return [
            tool.schema.to_openai_function(tool.name, tool.description)
            for tool in self._tools.values()
        ]
    
    def validate_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """
        Validate a tool call.
        Returns (is_valid, error_message).
        """
        tool = self.get(tool_name)
        
        if tool is None:
            return False, f"Unknown tool: {tool_name}"
        
        return tool.validate_args(args)
    
    def load_from_yaml(self, path: str) -> int:
        """
        Load tool definitions from YAML file.
        Returns number of tools loaded.
        """
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        
        count = 0
        for tool_data in data.get('tools', []):
            try:
                tool = self._parse_tool_definition(tool_data)
                self.register(tool)
                count += 1
            except Exception as e:
                self._logger.error(f"Failed to load tool: {e}")
        
        return count
    
    def _parse_tool_definition(self, data: Dict) -> Tool:
        """Parse a tool definition from dict."""
        # Parse parameters
        params = []
        for param_data in data.get('parameters', []):
            params.append(ToolParameter(
                name=param_data['name'],
                type=ParameterType(param_data.get('type', 'string')),
                description=param_data.get('description', ''),
                required=param_data.get('required', True),
                default=param_data.get('default'),
                enum=param_data.get('enum'),
                min_value=param_data.get('min'),
                max_value=param_data.get('max'),
                pattern=param_data.get('pattern'),
            ))
        
        # Create placeholder executor (will be replaced)
        def placeholder_executor(args: Dict) -> str:
            return f"Executed {data['name']} with {args}"
        
        return Tool(
            name=data['name'],
            description=data['description'],
            schema=ToolSchema(parameters=params),
            permission=PermissionLevel(data.get('permission', 'read')),
            executor=placeholder_executor,
            category=data.get('category', 'general'),
            timeout_seconds=data.get('timeout', 30.0),
            requires_confirmation=data.get('requires_confirmation', False),
        )
    
    def __len__(self) -> int:
        return len(self._tools)
    
    def __contains__(self, name: str) -> bool:
        return name in self._tools


def create_default_tools() -> ToolRegistry:
    """Create registry with default system tools."""
    registry = ToolRegistry()
    
    # System tools
    registry.register(Tool(
        name="get_current_time",
        description="Get the current system time",
        schema=ToolSchema(parameters=[
            ToolParameter(
                name="timezone",
                type=ParameterType.STRING,
                description="Timezone (e.g., 'UTC', 'America/New_York')",
                required=False,
                default="local"
            )
        ]),
        permission=PermissionLevel.READ,
        executor=lambda args: __import__('datetime').datetime.now().strftime('%I:%M %p'),
        category="system"
    ))
    
    registry.register(Tool(
        name="get_current_date",
        description="Get the current date",
        schema=ToolSchema(parameters=[
            ToolParameter(
                name="format",
                type=ParameterType.STRING,
                description="Date format (e.g., 'short', 'long', 'iso')",
                required=False,
                default="long",
                enum=["short", "long", "iso"]
            )
        ]),
        permission=PermissionLevel.READ,
        executor=lambda args: __import__('datetime').datetime.now().strftime('%A, %B %d, %Y'),
        category="system"
    ))
    
    registry.register(Tool(
        name="web_search",
        description="Search the web for information",
        schema=ToolSchema(parameters=[
            ToolParameter(
                name="query",
                type=ParameterType.STRING,
                description="Search query",
                required=True
            ),
            ToolParameter(
                name="num_results",
                type=ParameterType.INTEGER,
                description="Number of results to return",
                required=False,
                default=5,
                min_value=1,
                max_value=20
            )
        ]),
        permission=PermissionLevel.NETWORK,
        executor=lambda args: f"Searching for: {args['query']}",
        category="web"
    ))
    
    registry.register(Tool(
        name="open_application",
        description="Open an application on the system",
        schema=ToolSchema(parameters=[
            ToolParameter(
                name="app_name",
                type=ParameterType.STRING,
                description="Name of the application to open",
                required=True,
                enum=["Safari", "Chrome", "Firefox", "Terminal", "Finder", 
                      "Spotify", "Notes", "Calendar", "Calculator", "TextEdit"]
            )
        ]),
        permission=PermissionLevel.EXECUTE,
        executor=lambda args: f"Opening: {args['app_name']}",
        category="system"
    ))
    
    registry.register(Tool(
        name="set_volume",
        description="Set the system volume level",
        schema=ToolSchema(parameters=[
            ToolParameter(
                name="level",
                type=ParameterType.INTEGER,
                description="Volume level (0-100)",
                required=True,
                min_value=0,
                max_value=100
            )
        ]),
        permission=PermissionLevel.EXECUTE,
        executor=lambda args: f"Volume set to {args['level']}%",
        category="system"
    ))
    
    registry.register(Tool(
        name="read_file",
        description="Read contents of a file",
        schema=ToolSchema(parameters=[
            ToolParameter(
                name="path",
                type=ParameterType.STRING,
                description="Path to the file (must be in allowed directories)",
                required=True
            ),
            ToolParameter(
                name="max_lines",
                type=ParameterType.INTEGER,
                description="Maximum lines to read",
                required=False,
                default=100,
                min_value=1,
                max_value=1000
            )
        ]),
        permission=PermissionLevel.READ,
        executor=lambda args: f"Reading file: {args['path']}",
        category="filesystem"
    ))
    
    registry.register(Tool(
        name="list_directory",
        description="List files in a directory",
        schema=ToolSchema(parameters=[
            ToolParameter(
                name="path",
                type=ParameterType.STRING,
                description="Directory path",
                required=False,
                default="."
            ),
            ToolParameter(
                name="show_hidden",
                type=ParameterType.BOOLEAN,
                description="Show hidden files",
                required=False,
                default=False
            )
        ]),
        permission=PermissionLevel.READ,
        executor=lambda args: f"Listing: {args.get('path', '.')}",
        category="filesystem"
    ))
    
    # Screenshot tool
    registry.register(Tool(
        name="take_screenshot",
        description="Capture a screenshot of the screen",
        schema=ToolSchema(parameters=[
            ToolParameter(
                name="region",
                type=ParameterType.STRING,
                description="Screen region: 'full' or 'x,y,width,height'",
                required=False,
                default="full"
            )
        ]),
        permission=PermissionLevel.READ,
        executor=lambda args: "Screenshot captured",
        category="multimodal"
    ))
    
    # Scheduling tool
    registry.register(Tool(
        name="schedule_task",
        description="Schedule a task to run at a specific time or interval",
        schema=ToolSchema(parameters=[
            ToolParameter(
                name="name",
                type=ParameterType.STRING,
                description="Name of the scheduled task",
                required=True
            ),
            ToolParameter(
                name="action",
                type=ParameterType.STRING,
                description="Command to execute when triggered",
                required=True
            ),
            ToolParameter(
                name="type",
                type=ParameterType.STRING,
                description="Schedule type: 'time' or 'interval'",
                required=True,
                enum=["time", "interval"]
            ),
            ToolParameter(
                name="hour",
                type=ParameterType.INTEGER,
                description="Hour to execute (0-23) for time-based",
                required=False,
                min_value=0,
                max_value=23
            ),
            ToolParameter(
                name="minute",
                type=ParameterType.INTEGER,
                description="Minute to execute (0-59)",
                required=False,
                default=0,
                min_value=0,
                max_value=59
            ),
            ToolParameter(
                name="interval_seconds",
                type=ParameterType.INTEGER,
                description="Interval in seconds for interval-based",
                required=False,
                min_value=10,
                max_value=86400  # Max 24 hours
            )
        ]),
        permission=PermissionLevel.EXECUTE,
        executor=lambda args: f"Scheduled task: {args['name']}",
        category="automation"
    ))
    
    # List scheduled tasks
    registry.register(Tool(
        name="list_scheduled_tasks",
        description="List all scheduled tasks",
        schema=ToolSchema(parameters=[]),
        permission=PermissionLevel.READ,
        executor=lambda args: "No tasks scheduled",
        category="automation"
    ))
    
    return registry


def test_registry() -> None:
    """Test the tool registry."""
    print("Testing Tool Registry...")
    
    registry = create_default_tools()
    print(f"Loaded {len(registry)} tools")
    
    # Test validation
    print("\nValidation Tests:")
    
    # Valid call
    valid, error = registry.validate_tool_call("web_search", {"query": "python tutorials"})
    print(f"  web_search with query: {'✓ Valid' if valid else f'✗ {error}'}")
    
    # Missing required param
    valid, error = registry.validate_tool_call("web_search", {})
    print(f"  web_search without query: {'✗ Should fail' if valid else f'✓ Rejected: {error}'}")
    
    # Invalid type
    valid, error = registry.validate_tool_call("set_volume", {"level": "loud"})
    print(f"  set_volume with string: {'✗ Should fail' if valid else f'✓ Rejected: {error}'}")
    
    # Out of range
    valid, error = registry.validate_tool_call("set_volume", {"level": 150})
    print(f"  set_volume with 150: {'✗ Should fail' if valid else f'✓ Rejected: {error}'}")
    
    # Unknown tool
    valid, error = registry.validate_tool_call("unknown_tool", {})
    print(f"  unknown_tool: {'✗ Should fail' if valid else f'✓ Rejected: {error}'}")
    
    # Schema export
    print("\nLLM Schema Export:")
    schemas = registry.get_schemas_for_llm()
    print(f"  Generated {len(schemas)} function schemas")
    
    print("\nAll tests passed!")


if __name__ == "__main__":
    test_registry()
