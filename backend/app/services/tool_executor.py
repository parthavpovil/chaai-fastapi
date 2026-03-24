"""
Tool Executor Service
Executes external HTTP tool calls on behalf of an AI agent
"""
import re
import time
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from app.models.ai_agent import AIAgentTool
from app.services.encryption import decrypt_credential


MAX_RESPONSE_CHARS = 6000  # ~2000 tokens


@dataclass
class ToolResult:
    success: bool
    data: Any
    error: Optional[str]
    latency_ms: int
    status_code: Optional[int] = None


class ToolExecutor:
    """Executes an AIAgentTool HTTP call with parameter substitution and response extraction."""

    async def execute(self, tool: AIAgentTool, params: Dict[str, Any]) -> ToolResult:
        start = time.monotonic()
        try:
            url = self._resolve_url(tool.endpoint_url, params)
            headers = self._decrypt_headers(tool.headers or {})
            body = self._build_body(tool.body_template, params) if tool.body_template else None

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.request(
                    method=tool.method.upper(),
                    url=url,
                    headers=headers,
                    json=body if tool.method.upper() not in ("GET", "DELETE") else None,
                    params=params if tool.method.upper() in ("GET", "DELETE") else None,
                )

            latency_ms = int((time.monotonic() - start) * 1000)
            response.raise_for_status()

            try:
                data = response.json()
            except Exception:
                data = response.text

            if tool.response_path:
                data = self._extract_path(data, tool.response_path)

            # Truncate to protect token budget
            if isinstance(data, str) and len(data) > MAX_RESPONSE_CHARS:
                data = data[:MAX_RESPONSE_CHARS] + "... [truncated]"
            elif not isinstance(data, str):
                serialized = json.dumps(data)
                if len(serialized) > MAX_RESPONSE_CHARS:
                    data = serialized[:MAX_RESPONSE_CHARS] + "... [truncated]"

            return ToolResult(success=True, data=data, error=None, latency_ms=latency_ms, status_code=response.status_code)

        except httpx.HTTPStatusError as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                success=False,
                data=None,
                error=f"HTTP {e.response.status_code}: {e.response.text[:500]}",
                latency_ms=latency_ms,
                status_code=e.response.status_code,
            )
        except httpx.TimeoutException:
            latency_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(success=False, data=None, error="Request timed out after 10s", latency_ms=latency_ms)
        except Exception as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(success=False, data=None, error=str(e), latency_ms=latency_ms)

    def _resolve_url(self, template: str, params: Dict[str, Any]) -> str:
        """Replace {variable} placeholders in the URL."""
        def replace(match):
            key = match.group(1)
            return str(params.get(key, match.group(0)))
        return re.sub(r"\{(\w+)\}", replace, template)

    def _decrypt_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Attempt to decrypt each header value (falls back to plaintext if not encrypted)."""
        decrypted = {}
        for key, value in headers.items():
            try:
                decrypted[key] = decrypt_credential(value)
            except Exception:
                decrypted[key] = value
        return decrypted

    def _build_body(self, template: Any, params: Dict[str, Any]) -> Any:
        """Substitute {variable} placeholders in a body template (JSON-safe)."""
        if isinstance(template, dict):
            return {k: self._build_body(v, params) for k, v in template.items()}
        if isinstance(template, list):
            return [self._build_body(item, params) for item in template]
        if isinstance(template, str):
            def replace(match):
                key = match.group(1)
                return str(params.get(key, match.group(0)))
            return re.sub(r"\{(\w+)\}", replace, template)
        return template

    def _extract_path(self, data: Any, path: str) -> Any:
        """Extract a nested value using dot-notation path (e.g. 'order.status')."""
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return current
        return current
