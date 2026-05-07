"""
Escalation Classification Service
LLM-based escalation detection with keyword matching and confidence scoring
"""
import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

import json
from app.services.ai_provider import llm_provider, AIProviderError
from app.models.message import Message


class EscalationError(Exception):
    """Base exception for escalation processing errors"""
    pass


class EscalationClassifier:
    """
    Escalation classification service using LLM and keyword detection
    Identifies when customer messages require human agent intervention
    """
    
    # Explicit escalation keywords
    ESCALATION_KEYWORDS = [
        # Direct requests for human help
        'human', 'agent', 'manager', 'supervisor', 'person', 'representative',
        'speak to someone', 'talk to someone', 'real person', 'live chat',
        
        # Frustration indicators
        'frustrated', 'angry', 'upset', 'disappointed', 'terrible', 'awful',
        'horrible', 'worst', 'hate', 'disgusted', 'furious', 'livid',
        
        # Urgency indicators
        'urgent', 'emergency', 'asap', 'immediately', 'right now', 'critical',
        'important', 'serious', 'problem', 'issue', 'broken', 'not working',
        
        # Complaint indicators
        'complaint', 'complain', 'refund', 'cancel', 'unsubscribe', 'dispute',
        'chargeback', 'lawyer', 'legal', 'sue', 'court', 'attorney',
        
        # Dissatisfaction
        'unhappy', 'unsatisfied', 'disappointed', 'poor service', 'bad experience',
        'not helpful', 'useless', 'waste of time'
    ]
    
    # High confidence threshold for automatic escalation
    HIGH_CONFIDENCE_THRESHOLD = 0.8
    
    # Medium confidence threshold for flagging
    MEDIUM_CONFIDENCE_THRESHOLD = 0.6
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    def detect_explicit_keywords(self, message: str, custom_keywords: List[str] = None) -> Tuple[bool, List[str], float]:
        """
        Detect explicit escalation keywords in message

        Args:
            message: Message content
            custom_keywords: Workspace-configured keywords (overrides defaults if provided)

        Returns:
            Tuple of (has_keywords, found_keywords, confidence_score)
        """
        keyword_list = custom_keywords if custom_keywords else self.ESCALATION_KEYWORDS
        message_lower = message.lower()
        found_keywords = []

        for keyword in keyword_list:
            if keyword in message_lower:
                found_keywords.append(keyword)
        
        if not found_keywords:
            return False, [], 0.0
        
        # Calculate confidence based on keyword types and count
        confidence = min(0.3 + (len(found_keywords) * 0.2), 1.0)
        
        # Boost confidence for direct human requests
        human_keywords = ['human', 'agent', 'manager', 'supervisor', 'person', 'representative']
        if any(kw in found_keywords for kw in human_keywords):
            confidence = min(confidence + 0.4, 1.0)
        
        return True, found_keywords, confidence
    
    def build_classification_prompt(self, message: str, conversation_context: List[str] = None) -> str:
        """
        Build prompt for LLM escalation classification
        
        Args:
            message: Current message to classify
            conversation_context: Previous messages for context
        
        Returns:
            Classification prompt
        """
        prompt_parts = [
            "You are an escalation classifier for customer support. Analyze the following message "
            "and determine if it should be escalated to a human agent.",
            "",
            "Escalate if the message contains:",
            "- Direct requests for human help (agent, manager, person, etc.)",
            "- High frustration or anger",
            "- Urgent or critical issues",
            "- Complaints or legal threats",
            "- Complex problems that require human judgment",
            "",
            "Do NOT escalate for:",
            "- Simple questions that can be answered with documentation",
            "- Basic troubleshooting requests",
            "- General information requests",
            "- Polite feedback or suggestions",
            ""
        ]
        
        if conversation_context:
            prompt_parts.extend([
                "Previous conversation context:",
                *[f"- {ctx}" for ctx in conversation_context[-3:]],  # Last 3 messages
                ""
            ])
        
        prompt_parts.extend([
            f"Current message to classify: \"{message}\"",
            "",
            "Respond with a JSON object containing:",
            "- \"should_escalate\": boolean (true/false)",
            "- \"confidence\": number (0.0 to 1.0)",
            "- \"reason\": string (brief explanation)",
            "- \"category\": string (\"human_request\", \"frustration\", \"urgency\", \"complaint\", \"complex\", or \"none\")"
        ])
        
        return "\n".join(prompt_parts)
    
    async def classify_with_llm(
        self,
        message: str,
        conversation_context: List[str] = None,
    ) -> Tuple[Dict[str, Any], int, int]:
        """
        Classify message using LLM.

        Returns:
            Tuple of (classification_dict, input_tokens, output_tokens)

        Raises:
            EscalationError: If LLM classification fails
        """
        try:
            if not llm_provider:
                raise EscalationError("LLM provider not initialized")

            prompt = self.build_classification_prompt(message, conversation_context)

            # Use generate_response instead of classify_json so we get token counts
            raw_text, in_tok, out_tok = await llm_provider.generate_response(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.1,
            )

            # Strip markdown code fences if present (same logic as classify_json impls)
            text = raw_text.strip()
            for prefix in ("```json", "```"):
                if text.startswith(prefix):
                    text = text[len(prefix):]
            if text.endswith("```"):
                text = text[:-3]
            classification = json.loads(text.strip())

            # Validate response structure
            required_keys = ['should_escalate', 'confidence', 'reason', 'category']
            if not all(key in classification for key in required_keys):
                raise EscalationError(f"Invalid LLM response structure: {classification}")

            # Ensure confidence is in valid range
            confidence = float(classification['confidence'])
            confidence = max(0.0, min(1.0, confidence))
            classification['confidence'] = confidence

            return classification, in_tok, out_tok

        except (json.JSONDecodeError, ValueError) as e:
            raise EscalationError(f"LLM returned invalid JSON: {str(e)}")
        except AIProviderError as e:
            raise EscalationError(f"LLM classification failed: {str(e)}")
        except Exception as e:
            raise EscalationError(f"LLM classification error: {str(e)}")
    
    # Sensitivity → confidence threshold multipliers
    SENSITIVITY_THRESHOLDS = {
        "low":    1.3,   # harder to trigger escalation
        "medium": 1.0,   # default
        "high":   0.7,   # easier to trigger escalation
    }

    async def classify_message(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        use_llm: bool = True,
        workspace_keywords: List[str] = None,
        sensitivity: str = "medium",
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Complete escalation classification pipeline

        Args:
            message: Message to classify
            conversation_id: Optional conversation ID for context
            use_llm: Whether to use LLM classification (fallback to keywords only)
            workspace_keywords: Custom keywords from workspace settings (overrides defaults)
            sensitivity: Workspace sensitivity setting ("low", "medium", "high")

        Returns:
            Classification result with escalation decision and metadata
        """
        try:
            # 1. Keyword detection (always performed, using workspace keywords if set)
            has_keywords, found_keywords, keyword_confidence = self.detect_explicit_keywords(
                message, custom_keywords=workspace_keywords
            )
            
            # 2. Get conversation context if available
            conversation_context = []
            if conversation_id:
                conversation_context = await self.get_conversation_context(conversation_id)
            
            # 3. LLM classification (if enabled and available)
            llm_result = None
            esc_in_tok, esc_out_tok = 0, 0
            if use_llm:
                try:
                    llm_result, esc_in_tok, esc_out_tok = await self.classify_with_llm(message, conversation_context)
                except EscalationError as e:
                    logger.warning(f"LLM classification failed, using keywords only: {e}")
            
            # 4. Combine results
            if llm_result:
                # Use LLM result as primary, boost with keywords
                should_escalate = llm_result['should_escalate']
                confidence = llm_result['confidence']
                reason = llm_result['reason']
                category = llm_result['category']
                
                # Boost confidence if keywords detected
                if has_keywords:
                    confidence = min(confidence + keyword_confidence * 0.3, 1.0)
                    if not should_escalate and keyword_confidence >= 0.5:
                        # Override LLM when any escalation keyword is detected; raise
                        # confidence to at least the medium threshold so the sensitivity
                        # filter below does not immediately reverse this decision.
                        should_escalate = True
                        confidence = max(confidence, self.MEDIUM_CONFIDENCE_THRESHOLD)
                        reason = f"Keyword override: {reason}"
            else:
                # Fallback to keyword-only classification
                should_escalate = has_keywords and keyword_confidence >= 0.5
                # Ensure confidence is at least the medium threshold so the sensitivity
                # filter below does not reverse a keyword-triggered decision.
                confidence = max(keyword_confidence, self.MEDIUM_CONFIDENCE_THRESHOLD) if should_escalate else keyword_confidence
                reason = f"Keywords detected: {', '.join(found_keywords)}" if found_keywords else "No escalation indicators"
                category = "human_request" if any(kw in ['human', 'agent', 'manager'] for kw in found_keywords) else "none"
            
            # Determine escalation type per requirements 4.2 and 4.3
            # Requirement 4.2: Explicit keywords (human, agent, manager) -> "explicit"
            # Requirement 4.3: Frustration/urgency patterns -> "implicit"
            escalation_type = None
            if should_escalate:
                # Check for explicit human request keywords
                human_keywords = ['human', 'agent', 'manager', 'supervisor', 'person', 'representative']
                if any(kw in found_keywords for kw in human_keywords):
                    escalation_type = "explicit"
                else:
                    # Frustration or urgency patterns
                    escalation_type = "implicit"
            
            # Apply sensitivity: adjust effective threshold before final decision
            sensitivity_multiplier = self.SENSITIVITY_THRESHOLDS.get(sensitivity, 1.0)
            effective_threshold = self.MEDIUM_CONFIDENCE_THRESHOLD * sensitivity_multiplier
            if should_escalate and confidence < effective_threshold:
                should_escalate = False
                reason = f"Below sensitivity threshold ({sensitivity}): {reason}"
                escalation_type = None

            # Log escalation classifier tokens
            if workspace_id and esc_in_tok > 0:
                from app.services.ai_agent_token_tracker import log_token_usage
                await log_token_usage(
                    db=self.db,
                    workspace_id=workspace_id,
                    model=getattr(llm_provider, "llm_model", "unknown"),
                    call_type="escalation_check",
                    call_source="escalation_check",
                    input_tokens=esc_in_tok,
                    output_tokens=esc_out_tok,
                    conversation_id=conversation_id,
                )

            return {
                'should_escalate': should_escalate,
                'confidence': confidence,
                'reason': reason,
                'category': category,
                'escalation_type': escalation_type,  # "explicit" or "implicit" per requirements
                'keywords_found': found_keywords,
                'keyword_confidence': keyword_confidence,
                'llm_used': llm_result is not None,
                'classification_method': 'hybrid' if llm_result else 'keywords_only',
                'sensitivity': sensitivity,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            raise EscalationError(f"Message classification failed: {str(e)}")
    
    async def get_conversation_context(self, conversation_id: str, limit: int = 5) -> List[str]:
        """
        Get recent conversation messages for context
        
        Args:
            conversation_id: Conversation ID
            limit: Maximum messages to retrieve
        
        Returns:
            List of recent message contents
        """
        try:
            from sqlalchemy import select, desc
            
            result = await self.db.execute(
                select(Message.content, Message.msg_type)
                .where(Message.conversation_id == conversation_id)
                .order_by(desc(Message.created_at))
                .limit(limit)
            )
            
            messages = result.fetchall()
            context = []
            
            for content, msg_type in reversed(messages):  # Chronological order
                prefix = "Customer" if msg_type == "user" else "Assistant"
                context.append(f"{prefix}: {content}")
            
            return context
            
        except Exception as e:
            logger.warning(f"Failed to get conversation context: {e}")
            return []
    
    def get_escalation_priority(self, classification: Dict[str, Any]) -> str:
        """
        Determine escalation priority based on classification
        
        Args:
            classification: Classification result
        
        Returns:
            Priority level ("high", "medium", "low")
        """
        confidence = classification['confidence']
        category = classification['category']
        keywords = classification.get('keywords_found', [])
        
        # High priority conditions
        if confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
            return "high"
        
        if category in ['complaint', 'urgency'] and confidence >= 0.7:
            return "high"
        
        # Check for urgent keywords
        urgent_keywords = ['emergency', 'urgent', 'critical', 'asap', 'immediately']
        if any(kw in keywords for kw in urgent_keywords):
            return "high"
        
        # Medium priority conditions
        if confidence >= self.MEDIUM_CONFIDENCE_THRESHOLD:
            return "medium"
        
        if category in ['frustration', 'human_request'] and confidence >= 0.5:
            return "medium"
        
        return "low"


# ─── Convenience Functions ────────────────────────────────────────────────────

async def classify_message_for_escalation(
    db: AsyncSession,
    message: str,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to classify a message for escalation
    
    Args:
        db: Database session
        message: Message content to classify
        conversation_id: Optional conversation ID for context
    
    Returns:
        Classification result with escalation decision
    
    Raises:
        EscalationError: If classification fails
    """
    classifier = EscalationClassifier(db)
    classification = await classifier.classify_message(message, conversation_id)
    
    # Add priority level
    classification['priority'] = classifier.get_escalation_priority(classification)
    
    return classification


async def should_escalate_message(
    db: AsyncSession,
    message: str,
    conversation_id: Optional[str] = None,
    confidence_threshold: float = 0.6
) -> bool:
    """
    Simple boolean check for message escalation
    
    Args:
        db: Database session
        message: Message content
        conversation_id: Optional conversation ID
        confidence_threshold: Minimum confidence for escalation
    
    Returns:
        True if message should be escalated
    """
    try:
        classification = await classify_message_for_escalation(db, message, conversation_id)
        return (
            classification['should_escalate'] and 
            classification['confidence'] >= confidence_threshold
        )
    except EscalationError:
        # Fallback to keyword-only detection on error
        classifier = EscalationClassifier(db)
        has_keywords, _, confidence = classifier.detect_explicit_keywords(message)
        return has_keywords and confidence >= confidence_threshold