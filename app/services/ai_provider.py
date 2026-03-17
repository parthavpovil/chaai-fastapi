"""
AI Provider Abstraction Layer
Unified interface for multiple AI providers (Google, OpenAI, Groq)
"""
import os
import json
from typing import Protocol, runtime_checkable, List, Dict, Any, Tuple
from abc import ABC, abstractmethod

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
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            self.llm_model = "gpt-4o-mini"
            self.embedding_model = "text-embedding-3-small"
        except ImportError:
            raise AIProviderError("openai package not installed")
        except Exception as e:
            raise AIProviderAuthError(f"Failed to initialize OpenAI: {str(e)}")
    
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding using OpenAI's embedding model"""
        try:
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            return response.data[0].embedding  # 1536 dimensions
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
    else:
        raise ValueError(f"Unknown AI_PROVIDER: '{provider}'. Valid: google, openai, groq")


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


# ─── Singletons ───────────────────────────────────────────────────────────────
# Created once at startup, reused for all requests

try:
    llm_provider: AIProvider = get_llm_provider()
    embedding_provider: AIProvider = get_embedding_provider()
except Exception as e:
    # Log error but don't crash on startup - providers will be initialized on first use
    print(f"Warning: Failed to initialize AI providers: {e}")
    llm_provider = None
    embedding_provider = None