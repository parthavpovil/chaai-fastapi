"""
AI Provider Abstraction Layer
Unified interface for multiple AI providers (Google, OpenAI, Groq, Anthropic)
"""
import os
import json
import logging
from typing import Optional, Protocol, runtime_checkable, List, Dict, Any, Tuple
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

from app.config import settings


@runtime_checkable
class AIProvider(Protocol):
    """Protocol defining the AI provider interface"""

    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for text"""
        ...

    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7
    ) -> Tuple[str, int, int]:
        """
        Generate LLM response

        Returns:
            Tuple of (response_text, input_tokens, output_tokens)
        """
        ...

    async def classify_json(self, prompt: str) -> Dict[str, Any]:
        """Generate structured JSON response for classification tasks"""
        ...

    async def generate_response_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> Tuple[str, Optional[Dict[str, Any]], int, int]:
        """
        Generate LLM response with tool-calling support.

        Returns:
            Tuple of (text_response, tool_call_or_None, input_tokens, output_tokens)
            tool_call = {"name": str, "params": dict} or None
        """
        ...


class AIProviderError(Exception):
    """Base exception for AI provider errors"""
    pass


class AIProviderRateLimitError(AIProviderError):
    """Rate limit exceeded error"""
    pass


class AIProviderAuthError(AIProviderError):
    """Authentication error"""
    pass


class AIProviderUnavailableError(AIProviderError):
    """Service unavailable error"""
    pass


# ─── Google Provider ──────────────────────────────────────────────────────────

class GoogleProvider:
    """
    Google AI Provider
    LLM: gemini-2.0-flash
    Embeddings: gemini-embedding-001 (3072 dimensions)
    """
    
    def __init__(self):
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.GOOGLE_API_KEY)
            self.genai = genai
            self.llm_model = "gemini-2.0-flash"
            self.embedding_model = "models/text-embedding-004"  # Updated model
        except ImportError:
            raise AIProviderError("google-generativeai package not installed")
        except Exception as e:
            raise AIProviderAuthError(f"Failed to initialize Google AI: {str(e)}")
    
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding using Google's embedding model"""
        try:
            result = self.genai.embed_content(
                model=self.embedding_model,
                content=text,
                task_type="retrieval_document"
            )
            return result["embedding"]  # 3072 dimensions
        except Exception as e:
            if "quota" in str(e).lower() or "rate" in str(e).lower():
                raise AIProviderRateLimitError(f"Google AI rate limit: {str(e)}")
            elif "auth" in str(e).lower() or "key" in str(e).lower():
                raise AIProviderAuthError(f"Google AI auth error: {str(e)}")
            else:
                raise AIProviderError(f"Google AI embedding error: {str(e)}")
    
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7
    ) -> Tuple[str, int, int]:
        """Generate response using Gemini model"""
        try:
            model = self.genai.GenerativeModel(
                self.llm_model,
                generation_config={
                    "max_output_tokens": max_tokens,
                    "temperature": temperature
                }
            )
            
            # Convert OpenAI message format to Gemini format
            gemini_messages = self._convert_messages_to_gemini(messages)
            
            response = model.generate_content(gemini_messages)
            
            # Extract token usage
            input_tokens = response.usage_metadata.prompt_token_count
            output_tokens = response.usage_metadata.candidates_token_count
            
            return response.text, input_tokens, output_tokens
            
        except Exception as e:
            if "quota" in str(e).lower() or "rate" in str(e).lower():
                raise AIProviderRateLimitError(f"Google AI rate limit: {str(e)}")
            elif "auth" in str(e).lower() or "key" in str(e).lower():
                raise AIProviderAuthError(f"Google AI auth error: {str(e)}")
            else:
                raise AIProviderError(f"Google AI response error: {str(e)}")
    
    async def classify_json(self, prompt: str) -> Dict[str, Any]:
        """Generate structured JSON response for classification"""
        try:
            model = self.genai.GenerativeModel(
                self.llm_model,
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 150
                }
            )
            
            response = model.generate_content(prompt)
            
            # Strip markdown code blocks if present
            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            
            return json.loads(text)
            
        except json.JSONDecodeError as e:
            raise AIProviderError(f"Invalid JSON response from Google AI: {str(e)}")
        except Exception as e:
            if "quota" in str(e).lower() or "rate" in str(e).lower():
                raise AIProviderRateLimitError(f"Google AI rate limit: {str(e)}")
            elif "auth" in str(e).lower() or "key" in str(e).lower():
                raise AIProviderAuthError(f"Google AI auth error: {str(e)}")
            else:
                raise AIProviderError(f"Google AI classification error: {str(e)}")
    
    async def generate_response_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> Tuple[str, Optional[Dict[str, Any]], int, int]:
        """Generate response with Gemini function calling"""
        try:
            from google.generativeai.types import FunctionDeclaration, Tool as GeminiTool

            # Build Gemini tool declarations
            declarations = []
            for tool in tools:
                props = {}
                required = []
                for param in tool.get("parameters", []):
                    props[param["name"]] = {"type": param.get("type", "string"), "description": param.get("description", "")}
                    if param.get("required", True):
                        required.append(param["name"])
                declarations.append(FunctionDeclaration(
                    name=tool["name"],
                    description=tool["description"],
                    parameters={"type": "object", "properties": props, "required": required},
                ))

            gemini_tool = GeminiTool(function_declarations=declarations)
            model = self.genai.GenerativeModel(
                self.llm_model,
                tools=[gemini_tool],
                generation_config={"max_output_tokens": max_tokens, "temperature": temperature},
            )
            gemini_messages = self._convert_messages_to_gemini(messages)
            response = model.generate_content(gemini_messages)

            input_tokens = response.usage_metadata.prompt_token_count
            output_tokens = response.usage_metadata.candidates_token_count

            # Check for function call
            for part in response.candidates[0].content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    return "", {"name": fc.name, "params": dict(fc.args)}, input_tokens, output_tokens

            return response.text, None, input_tokens, output_tokens

        except Exception as e:
            if "quota" in str(e).lower() or "rate" in str(e).lower():
                raise AIProviderRateLimitError(f"Google AI rate limit: {str(e)}")
            raise AIProviderError(f"Google AI tool-calling error: {str(e)}")

    def _convert_messages_to_gemini(self, messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Convert OpenAI message format to Gemini format"""
        gemini_messages = []
        for msg in messages:
            role = "user" if msg["role"] in ("user", "system") else "model"
            gemini_messages.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })
        return gemini_messages


# ─── OpenAI Provider ──────────────────────────────────────────────────────────

class OpenAIProvider:
    """
    OpenAI Provider
    LLM: gpt-4o-mini
    Embeddings: text-embedding-3-small (1536 dimensions)
    """
    
    def __init__(self):
        try:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60.0)
            self.llm_model = "gpt-4o-mini"
            self.embedding_model = "text-embedding-3-small"
        except ImportError:
            raise AIProviderError("openai package not installed")
        except Exception as e:
            raise AIProviderAuthError(f"Failed to initialize OpenAI: {str(e)}")
    
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding using OpenAI's embedding model"""
        embeddings = await self.generate_batch_embeddings([text])
        return embeddings[0]

    async def generate_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts in a single API call"""
        try:
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=texts
            )
            return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
        except Exception as e:
            if "rate_limit" in str(e).lower():
                raise AIProviderRateLimitError(f"OpenAI rate limit: {str(e)}")
            elif "auth" in str(e).lower() or "key" in str(e).lower():
                raise AIProviderAuthError(f"OpenAI auth error: {str(e)}")
            else:
                raise AIProviderError(f"OpenAI embedding error: {str(e)}")
    
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7
    ) -> Tuple[str, int, int]:
        """Generate response using GPT model"""
        try:
            response = await self.client.chat.completions.create(
                model=self.llm_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            
            return (
                response.choices[0].message.content,
                response.usage.prompt_tokens,
                response.usage.completion_tokens
            )
            
        except Exception as e:
            if "rate_limit" in str(e).lower():
                raise AIProviderRateLimitError(f"OpenAI rate limit: {str(e)}")
            elif "auth" in str(e).lower() or "key" in str(e).lower():
                raise AIProviderAuthError(f"OpenAI auth error: {str(e)}")
            else:
                raise AIProviderError(f"OpenAI response error: {str(e)}")
    
    async def classify_json(self, prompt: str) -> Dict[str, Any]:
        """Generate structured JSON response for classification"""
        try:
            response = await self.client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=150,
                temperature=0.1
            )

            return json.loads(response.choices[0].message.content)

        except json.JSONDecodeError as e:
            raise AIProviderError(f"Invalid JSON response from OpenAI: {str(e)}")
        except Exception as e:
            if "rate_limit" in str(e).lower():
                raise AIProviderRateLimitError(f"OpenAI rate limit: {str(e)}")
            elif "auth" in str(e).lower() or "key" in str(e).lower():
                raise AIProviderAuthError(f"OpenAI auth error: {str(e)}")
            else:
                raise AIProviderError(f"OpenAI classification error: {str(e)}")

    async def generate_response_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> Tuple[str, Optional[Dict[str, Any]], int, int]:
        """Generate response with OpenAI function calling"""
        try:
            openai_tools = []
            for tool in tools:
                props = {}
                required = []
                for param in tool.get("parameters", []):
                    props[param["name"]] = {"type": param.get("type", "string"), "description": param.get("description", "")}
                    if param.get("required", True):
                        required.append(param["name"])
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": {"type": "object", "properties": props, "required": required},
                    },
                })

            response = await self.client.chat.completions.create(
                model=self.llm_model,
                messages=messages,
                tools=openai_tools,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            message = response.choices[0].message
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens

            if message.tool_calls:
                tc = message.tool_calls[0]
                return "", {"name": tc.function.name, "params": json.loads(tc.function.arguments)}, input_tokens, output_tokens

            return message.content or "", None, input_tokens, output_tokens

        except Exception as e:
            if "rate_limit" in str(e).lower():
                raise AIProviderRateLimitError(f"OpenAI rate limit: {str(e)}")
            elif "auth" in str(e).lower() or "key" in str(e).lower():
                raise AIProviderAuthError(f"OpenAI auth error: {str(e)}")
            raise AIProviderError(f"OpenAI tool-calling error: {str(e)}")


# ─── Groq Provider ────────────────────────────────────────────────────────────

class GroqProvider:
    """
    Groq Provider
    LLM: llama-3.3-70b-versatile (free tier: 14,400 req/day)
    Embeddings: NOT SUPPORTED — falls back to EMBEDDING_PROVIDER setting
    """
    
    def __init__(self):
        try:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(
                api_key=settings.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1"
            )
            self.llm_model = "llama-3.3-70b-versatile"
        except ImportError:
            raise AIProviderError("openai package not installed (required for Groq)")
        except Exception as e:
            raise AIProviderAuthError(f"Failed to initialize Groq: {str(e)}")
    
    async def generate_embedding(self, text: str) -> List[float]:
        """Groq does not support embeddings - use embedding provider"""
        embedding_provider = get_embedding_provider()
        return await embedding_provider.generate_embedding(text)
    
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7
    ) -> Tuple[str, int, int]:
        """Generate response using Llama model"""
        try:
            response = await self.client.chat.completions.create(
                model=self.llm_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            
            return (
                response.choices[0].message.content,
                response.usage.prompt_tokens,
                response.usage.completion_tokens
            )
            
        except Exception as e:
            if "rate_limit" in str(e).lower():
                raise AIProviderRateLimitError(f"Groq rate limit: {str(e)}")
            elif "auth" in str(e).lower() or "key" in str(e).lower():
                raise AIProviderAuthError(f"Groq auth error: {str(e)}")
            else:
                raise AIProviderError(f"Groq response error: {str(e)}")
    
    async def classify_json(self, prompt: str) -> Dict[str, Any]:
        """Generate structured JSON response for classification"""
        try:
            response = await self.client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=150,
                temperature=0.1
            )

            return json.loads(response.choices[0].message.content)

        except json.JSONDecodeError as e:
            raise AIProviderError(f"Invalid JSON response from Groq: {str(e)}")
        except Exception as e:
            if "rate_limit" in str(e).lower():
                raise AIProviderRateLimitError(f"Groq rate limit: {str(e)}")
            elif "auth" in str(e).lower() or "key" in str(e).lower():
                raise AIProviderAuthError(f"Groq auth error: {str(e)}")
            else:
                raise AIProviderError(f"Groq classification error: {str(e)}")

    async def generate_response_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> Tuple[str, Optional[Dict[str, Any]], int, int]:
        """Groq supports OpenAI-compatible tool calling"""
        try:
            openai_tools = []
            for tool in tools:
                props = {}
                required = []
                for param in tool.get("parameters", []):
                    props[param["name"]] = {"type": param.get("type", "string"), "description": param.get("description", "")}
                    if param.get("required", True):
                        required.append(param["name"])
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": {"type": "object", "properties": props, "required": required},
                    },
                })

            response = await self.client.chat.completions.create(
                model=self.llm_model,
                messages=messages,
                tools=openai_tools,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            message = response.choices[0].message
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens

            if message.tool_calls:
                tc = message.tool_calls[0]
                return "", {"name": tc.function.name, "params": json.loads(tc.function.arguments)}, input_tokens, output_tokens

            return message.content or "", None, input_tokens, output_tokens

        except Exception as e:
            if "rate_limit" in str(e).lower():
                raise AIProviderRateLimitError(f"Groq rate limit: {str(e)}")
            raise AIProviderError(f"Groq tool-calling error: {str(e)}")


# ─── Anthropic Provider ───────────────────────────────────────────────────────

class AnthropicProvider:
    """
    Anthropic Provider
    LLM: claude-haiku-4-5 (default)
    Embeddings: NOT SUPPORTED — falls back to Google embeddings
    """

    def __init__(self, api_key: str = "", model: str = "claude-haiku-4-5"):
        try:
            import anthropic as anthropic_lib
            self.client = anthropic_lib.AsyncAnthropic(api_key=api_key or settings.ANTHROPIC_API_KEY)
            self.llm_model = model
        except ImportError:
            raise AIProviderError("anthropic package not installed — run: pip install anthropic>=0.40.0")
        except Exception as e:
            raise AIProviderAuthError(f"Failed to initialize Anthropic: {str(e)}")

    async def generate_embedding(self, text: str) -> List[float]:
        """Anthropic has no embeddings API — delegate to Google"""
        embedding_provider = get_embedding_provider()
        return await embedding_provider.generate_embedding(text)

    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7,
    ) -> Tuple[str, int, int]:
        """Generate response using Claude model"""
        try:
            # Extract system message if present
            system_content = ""
            chat_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    system_content = msg["content"]
                else:
                    chat_messages.append({"role": msg["role"], "content": msg["content"]})

            kwargs: Dict[str, Any] = {
                "model": self.llm_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": chat_messages,
            }
            if system_content:
                kwargs["system"] = system_content

            response = await self.client.messages.create(**kwargs)

            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            text = response.content[0].text if response.content else ""
            return text, input_tokens, output_tokens

        except Exception as e:
            if "rate_limit" in str(e).lower() or "overloaded" in str(e).lower():
                raise AIProviderRateLimitError(f"Anthropic rate limit: {str(e)}")
            elif "auth" in str(e).lower() or "api_key" in str(e).lower():
                raise AIProviderAuthError(f"Anthropic auth error: {str(e)}")
            raise AIProviderError(f"Anthropic response error: {str(e)}")

    async def classify_json(self, prompt: str) -> Dict[str, Any]:
        """Generate structured JSON response for classification"""
        try:
            response = await self.client.messages.create(
                model=self.llm_model,
                max_tokens=150,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            return json.loads(text.strip())
        except json.JSONDecodeError as e:
            raise AIProviderError(f"Invalid JSON response from Anthropic: {str(e)}")
        except Exception as e:
            raise AIProviderError(f"Anthropic classification error: {str(e)}")

    async def generate_response_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> Tuple[str, Optional[Dict[str, Any]], int, int]:
        """Generate response with Anthropic tool_use blocks"""
        try:
            # Build Anthropic tool schemas
            anthropic_tools = []
            for tool in tools:
                props = {}
                required = []
                for param in tool.get("parameters", []):
                    props[param["name"]] = {"type": param.get("type", "string"), "description": param.get("description", "")}
                    if param.get("required", True):
                        required.append(param["name"])
                anthropic_tools.append({
                    "name": tool["name"],
                    "description": tool["description"],
                    "input_schema": {"type": "object", "properties": props, "required": required},
                })

            system_content = ""
            chat_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    system_content = msg["content"]
                else:
                    chat_messages.append({"role": msg["role"], "content": msg["content"]})

            kwargs: Dict[str, Any] = {
                "model": self.llm_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": chat_messages,
                "tools": anthropic_tools,
            }
            if system_content:
                kwargs["system"] = system_content

            response = await self.client.messages.create(**kwargs)

            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens

            for block in response.content:
                if block.type == "tool_use":
                    return "", {"name": block.name, "params": dict(block.input)}, input_tokens, output_tokens

            text_blocks = [b.text for b in response.content if hasattr(b, "text")]
            return " ".join(text_blocks), None, input_tokens, output_tokens

        except Exception as e:
            if "rate_limit" in str(e).lower() or "overloaded" in str(e).lower():
                raise AIProviderRateLimitError(f"Anthropic rate limit: {str(e)}")
            elif "auth" in str(e).lower() or "api_key" in str(e).lower():
                raise AIProviderAuthError(f"Anthropic auth error: {str(e)}")
            raise AIProviderError(f"Anthropic tool-calling error: {str(e)}")


# ─── Factory Functions ────────────────────────────────────────────────────────

def get_llm_provider() -> AIProvider:
    """Returns the LLM provider based on AI_PROVIDER env variable."""
    provider = settings.AI_PROVIDER.lower()

    if provider == "google":
        return GoogleProvider()
    elif provider == "openai":
        return OpenAIProvider()
    elif provider == "groq":
        return GroqProvider()
    elif provider == "anthropic":
        return AnthropicProvider()
    else:
        raise ValueError(f"Unknown AI_PROVIDER: '{provider}'. Valid: google, openai, groq, anthropic")


def get_embedding_provider() -> AIProvider:
    """
    Returns the embedding provider based on EMBEDDING_PROVIDER env variable.
    Separate from LLM provider because switching embeddings requires DB migration.
    """
    provider = settings.EMBEDDING_PROVIDER.lower()
    
    if provider == "google":
        return GoogleProvider()
    elif provider == "openai":
        return OpenAIProvider()
    else:
        raise ValueError(f"Unknown EMBEDDING_PROVIDER: '{provider}'. Valid: google, openai")


# ─── Workspace-aware provider factory ────────────────────────────────────────

def get_llm_provider_for_workspace(workspace_metadata: dict) -> AIProvider:
    """
    Returns an LLM provider configured for a specific workspace.
    Falls back to the global settings if no workspace override is set.

    workspace_metadata keys:
      - "ai_provider": "google" | "openai" | "groq"
      - "ai_model": optional model name override
      - "ai_api_key": optional raw API key (plaintext after decryption)
    """
    if not workspace_metadata:
        return get_llm_provider()

    provider_name = workspace_metadata.get("ai_provider", "").lower()
    api_key = workspace_metadata.get("ai_api_key", "")

    if provider_name == "google":
        p = GoogleProvider.__new__(GoogleProvider)
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key or settings.GOOGLE_API_KEY)
            p.genai = genai
            p.llm_model = workspace_metadata.get("ai_model", "gemini-2.0-flash")
            p.embedding_model = "models/text-embedding-004"
        except Exception as e:
            raise AIProviderAuthError(f"Failed to initialize workspace Google provider: {e}")
        return p

    elif provider_name == "openai":
        p = OpenAIProvider.__new__(OpenAIProvider)
        try:
            import openai as openai_lib
            p.client = openai_lib.AsyncOpenAI(api_key=api_key or settings.OPENAI_API_KEY, timeout=60.0)
            p.llm_model = workspace_metadata.get("ai_model", "gpt-4o-mini")
            p.embedding_model = "text-embedding-3-small"
        except Exception as e:
            raise AIProviderAuthError(f"Failed to initialize workspace OpenAI provider: {e}")
        return p

    elif provider_name == "groq":
        p = GroqProvider.__new__(GroqProvider)
        try:
            from openai import AsyncOpenAI
            p.client = AsyncOpenAI(
                api_key=api_key or settings.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
            )
            p.llm_model = workspace_metadata.get("ai_model", "llama-3.3-70b-versatile")
        except Exception as e:
            raise AIProviderAuthError(f"Failed to initialize workspace Groq provider: {e}")
        return p

    elif provider_name == "anthropic":
        return AnthropicProvider(
            api_key=api_key or settings.ANTHROPIC_API_KEY,
            model=workspace_metadata.get("ai_model", "claude-haiku-4-5"),
        )

    # No workspace override — use global default
    return get_llm_provider()


# ─── Singletons ───────────────────────────────────────────────────────────────
# Created once at startup, reused for all requests

try:
    llm_provider: AIProvider = get_llm_provider()
    embedding_provider: AIProvider = get_embedding_provider()
except Exception as e:
    # Log error but don't crash on startup - providers will be initialized on first use
    logger.warning(f"Failed to initialize AI providers: {e}")
    llm_provider = None
    embedding_provider = None