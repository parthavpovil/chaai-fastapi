"""
AI Agent Pydantic Schemas
Request/response models for AI Agent API endpoints
"""
from typing import Optional, List, Any, Dict
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


# ─── Tool Schemas ─────────────────────────────────────────────────────────────

class ToolParameterSchema(BaseModel):
    name: str
    type: str  # string | integer | boolean | number
    required: bool = True
    description: str


class AIAgentToolCreate(BaseModel):
    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$", description="snake_case tool name")
    display_name: str = Field(..., max_length=100)
    description: str
    method: str = Field(default="GET", pattern="^(GET|POST|PUT|PATCH|DELETE)$")
    endpoint_url: str
    headers: Dict[str, str] = Field(default_factory=dict)
    body_template: Optional[Dict[str, Any]] = None
    parameters: List[ToolParameterSchema] = Field(default_factory=list)
    response_path: Optional[str] = None
    requires_confirmation: bool = False
    is_read_only: bool = True


class AIAgentToolUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    method: Optional[str] = Field(None, pattern="^(GET|POST|PUT|PATCH|DELETE)$")
    endpoint_url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    body_template: Optional[Dict[str, Any]] = None
    parameters: Optional[List[ToolParameterSchema]] = None
    response_path: Optional[str] = None
    requires_confirmation: Optional[bool] = None
    is_read_only: Optional[bool] = None
    is_active: Optional[bool] = None


class AIAgentToolResponse(BaseModel):
    id: UUID
    agent_id: UUID
    name: str
    display_name: str
    description: str
    method: str
    endpoint_url: str
    parameters: List[Dict[str, Any]]
    response_path: Optional[str]
    requires_confirmation: bool
    is_read_only: bool
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ToolTestRequest(BaseModel):
    params: Dict[str, Any] = Field(default_factory=dict)


class ToolTestResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    latency_ms: int
    status_code: Optional[int] = None


# ─── Guardrail Schemas ────────────────────────────────────────────────────────

class AIAgentGuardrailCreate(BaseModel):
    rule_type: str = Field(..., pattern="^(forbidden_topic|forbidden_action|required_escalation)$")
    description: str


class AIAgentGuardrailResponse(BaseModel):
    id: UUID
    agent_id: UUID
    rule_type: str
    description: str
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Agent Schemas ────────────────────────────────────────────────────────────

class AIAgentCreate(BaseModel):
    name: str = Field(..., max_length=100)
    system_prompt: str
    persona_name: Optional[str] = Field(None, max_length=50)
    persona_tone: str = Field(default="friendly", max_length=50)
    first_message: Optional[str] = None
    escalation_trigger: str = Field(default="low_confidence", max_length=50)
    escalation_message: str = Field(default="Let me connect you with a team member.")
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    max_turns: int = Field(default=10, ge=1, le=50)
    token_budget: int = Field(default=8000, ge=1000, le=32000)


class AIAgentUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    system_prompt: Optional[str] = None
    persona_name: Optional[str] = Field(None, max_length=50)
    persona_tone: Optional[str] = Field(None, max_length=50)
    first_message: Optional[str] = None
    escalation_trigger: Optional[str] = Field(None, max_length=50)
    escalation_message: Optional[str] = None
    confidence_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    max_turns: Optional[int] = Field(None, ge=1, le=50)
    token_budget: Optional[int] = Field(None, ge=1000, le=32000)
    is_active: Optional[bool] = None


class AIAgentResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    system_prompt: str
    persona_name: Optional[str]
    persona_tone: str
    first_message: Optional[str]
    escalation_trigger: str
    escalation_message: str
    confidence_threshold: float
    max_turns: int
    token_budget: int
    is_active: bool
    is_draft: bool
    created_at: datetime
    updated_at: datetime
    tools: List[AIAgentToolResponse] = []
    guardrails: List[AIAgentGuardrailResponse] = []

    class Config:
        from_attributes = True


# ─── Channel Assignment Schemas ───────────────────────────────────────────────

class ChannelAssignmentResponse(BaseModel):
    id: UUID
    agent_id: UUID
    channel_id: UUID
    priority: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Sandbox Schemas ──────────────────────────────────────────────────────────

class SandboxMessageRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None  # optional: resume sandbox session


class DebugInfo(BaseModel):
    tool_called: Optional[str] = None
    tool_params: Optional[Dict[str, Any]] = None
    tool_result: Optional[Any] = None
    tool_success: Optional[bool] = None
    tool_latency_ms: Optional[int] = None
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    turn_count: int
    escalated: bool


class SandboxMessageResponse(BaseModel):
    reply: str
    escalated: bool
    escalation_reason: Optional[str] = None
    debug: DebugInfo


# ─── Analytics Schemas ────────────────────────────────────────────────────────

class AgentAnalyticsResponse(BaseModel):
    agent_id: UUID
    total_conversations: int
    active_conversations: int
    escalated_conversations: int
    resolved_conversations: int
    total_turns: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    tool_calls_total: int
    tool_calls_success: int
    model_breakdown: List[Dict[str, Any]]


# ─── AI Pipeline Config Schemas ───────────────────────────────────────────────

class AIPipelineConfigUpdate(BaseModel):
    ai_mode: str = Field(..., pattern="^(rag|ai_agent)$")
    ai_provider: Optional[str] = Field(None, pattern="^(anthropic|openai|google)$")
    ai_model: Optional[str] = Field(None, max_length=100)
    ai_api_key: Optional[str] = Field(None, max_length=500)
