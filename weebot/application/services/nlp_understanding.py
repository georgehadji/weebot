"""
Enhanced Natural Language Understanding Module for Weebot

This module provides advanced natural language processing capabilities
to improve user communication and requirement understanding.
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import re


class IntentType(Enum):
    """Types of user intents that can be recognized."""
    RESEARCH = "research"
    ANALYSIS = "analysis"
    TASK_EXECUTION = "task_execution"
    INFORMATION_REQUEST = "information_request"
    CONTENT_CREATION = "content_creation"
    AUTOMATION = "automation"
    UNKNOWN = "unknown"


@dataclass
class PurposeAnalysis:
    """Detailed analysis of the user's underlying purpose."""
    primary_goal: str  # The main goal the user wants to achieve
    secondary_goals: List[str]  # Additional goals that support the primary goal
    motivation: str  # Why the user wants to achieve this goal
    expected_outcome: str  # What the user expects to get from this
    urgency_level: str  # How urgent this is (low, medium, high)
    success_criteria: List[str]  # How the user will measure success


@dataclass
class IntentRecognitionResult:
    """Result of intent recognition process."""
    intent: IntentType
    confidence: float  # 0.0 to 1.0
    entities: Dict[str, str]  # Named entities extracted from the text
    keywords: List[str]  # Important keywords identified
    action_items: List[str]  # Specific actions requested
    purpose_analysis: Optional[PurposeAnalysis] = None  # Detailed purpose analysis


class PurposeAnalyzer:
    """
    Analyzes the underlying purpose behind user requests.
    
    Identifies primary goals, motivations, expected outcomes, and success criteria
    to better understand what the user is really trying to achieve.
    """
    
    def __init__(self):
        # Patterns for identifying purposes
        self.goal_patterns = {
            "primary_goal": [
                r"need to ([^,.]+)", r"want to ([^,.]+)", r"would like to ([^,.]+)",
                r"trying to ([^,.]+)", r"looking to ([^,.]+)", r"aim to ([^,.]+)",
                r"goal is to ([^,.]+)", r"objective is ([^,.]+)"
            ],
            "motivation": [
                r"because ([^,.]+)", r"since ([^,.]+)", r"for ([^,.]+)",
                r"to ([^,.]+)", r"so that ([^,.]+)", r"in order to ([^,.]+)"
            ],
            "expected_outcome": [
                r"to get ([^,.]+)", r"to obtain ([^,.]+)", r"to achieve ([^,.]+)",
                r"to create ([^,.]+)", r"to develop ([^,.]+)", r"to produce ([^,.]+)"
            ],
            "success_criteria": [
                r"measured by ([^,.]+)", r"if ([^,.]+)", r"when ([^,.]+)",
                r"that ([^,.]+)", r"which ([^,.]+)", r"so ([^,.]+)"
            ]
        }
        
        # Urgency indicators
        self.urgency_indicators = {
            "high": [r"urgent", r"asap", r"immediately", r"right now", r"today", r"by end of day", r"crucial", r"critical"],
            "medium": [r"soon", r"quickly", r"this week", r"this month", r"important", r"necessary"],
            "low": [r"whenever", r"eventually", r"someday", r"later", r"optionally", r"if possible"]
        }
    
    def analyze_purpose(self, text: str) -> PurposeAnalysis:
        """
        Analyze the underlying purpose of the user's request.
        
        Args:
            text: The input text to analyze
            
        Returns:
            PurposeAnalysis with detailed purpose information
        """
        text_lower = text.lower()
        
        # Extract primary goal
        primary_goal = self._extract_primary_goal(text_lower)
        
        # Extract secondary goals
        secondary_goals = self._extract_secondary_goals(text_lower)
        
        # Extract motivation
        motivation = self._extract_motivation(text_lower)
        
        # Extract expected outcome
        expected_outcome = self._extract_expected_outcome(text_lower)
        
        # Determine urgency level
        urgency_level = self._determine_urgency(text_lower)
        
        # Extract success criteria
        success_criteria = self._extract_success_criteria(text_lower)
        
        return PurposeAnalysis(
            primary_goal=primary_goal or "Unknown goal",
            secondary_goals=secondary_goals,
            motivation=motivation or "Not specified",
            expected_outcome=expected_outcome or "Not specified",
            urgency_level=urgency_level,
            success_criteria=success_criteria
        )
    
    def _extract_primary_goal(self, text: str) -> str:
        """Extract the primary goal from the text."""
        for pattern in self.goal_patterns["primary_goal"]:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                return matches[0].strip()
        return ""
    
    def _extract_secondary_goals(self, text: str) -> List[str]:
        """Extract potential secondary goals."""
        # Look for additional goals in the text
        secondary_patterns = [
            r"also need to ([^,.]+)", r"additionally ([^,.]+)", r"plus ([^,.]+)",
            r"another thing ([^,.]+)", r"furthermore ([^,.]+)", r"besides ([^,.]+)"
        ]
        
        secondary_goals = []
        for pattern in secondary_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            secondary_goals.extend([match.strip() for match in matches])
        
        return secondary_goals
    
    def _extract_motivation(self, text: str) -> str:
        """Extract the motivation behind the request."""
        for pattern in self.goal_patterns["motivation"]:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                return matches[0].strip()
        return ""
    
    def _extract_expected_outcome(self, text: str) -> str:
        """Extract the expected outcome."""
        for pattern in self.goal_patterns["expected_outcome"]:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                return matches[0].strip()
        return ""
    
    def _determine_urgency(self, text: str) -> str:
        """Determine the urgency level of the request."""
        for level, patterns in self.urgency_indicators.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return level
        return "medium"  # Default to medium urgency
    
    def _extract_success_criteria(self, text: str) -> List[str]:
        """Extract success criteria."""
        success_criteria = []
        for pattern in self.goal_patterns["success_criteria"]:
            matches = re.findall(pattern, text, re.IGNORECASE)
            success_criteria.extend([match.strip() for match in matches])
        
        return success_criteria


class IntentRecognizer:
    """
    Recognizes user intents from natural language input.
    
    Uses pattern matching and keyword analysis to determine the user's
    primary intent and extract relevant information.
    """
    
    def __init__(self):
        # Define patterns for different intents
        self.patterns = {
            IntentType.RESEARCH: [
                r"research", r"investigate", r"find.*about", r"look.*up", 
                r"study", r"analyze.*topic", r"learn.*about", r"explore"
            ],
            IntentType.ANALYSIS: [
                r"analyze", r"analyze.*data", r"review", r"examine", 
                r"evaluate", r"assess", r"compare", r"benchmark"
            ],
            IntentType.TASK_EXECUTION: [
                r"execute", r"run", r"perform", r"do", r"complete", 
                r"finish", r"accomplish", r"carry.*out"
            ],
            IntentType.INFORMATION_REQUEST: [
                r"what.*is", r"tell.*me.*about", r"explain", r"describe", 
                r"define", r"how.*does", r"why.*is", r"when.*will"
            ],
            IntentType.CONTENT_CREATION: [
                r"create", r"write", r"generate", r"produce", r"make", 
                r"develop", r"compose", r"draft"
            ],
            IntentType.AUTOMATION: [
                r"automate", r"simplify", r"optimize", r"schedule", 
                r"organize", r"plan", r"arrange", r"coordinate"
            ]
        }
        
        # Common entity patterns
        self.entity_patterns = {
            "topic": [r"(?:about|on|regarding)\s+([^.!?]+)", r"(?:for|on)\s+([^.!?]+)"],
            "timeframe": [r"(?:in|during|over)\s+(?:the\s+)?(\w+\s+\w+|\w+)", r"by\s+(\w+\s+\w+|\w+)"],
            "location": [r"in\s+([^.!?]+)", r"at\s+([^.!?]+)"],
            "person": [r"(?:to|for|with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)"]
        }
        
        # Initialize purpose analyzer
        self.purpose_analyzer = PurposeAnalyzer()
    
    def recognize_intent(self, text: str) -> IntentRecognitionResult:
        """
        Recognize the intent from the given text.
        
        Args:
            text: The input text to analyze
            
        Returns:
            IntentRecognitionResult with the identified intent and details
        """
        text_lower = text.lower().strip()
        
        # Calculate scores for each intent
        intent_scores = {}
        for intent, patterns in self.patterns.items():
            score = 0
            matched_keywords = []
            
            for pattern in patterns:
                matches = re.findall(pattern, text_lower)
                score += len(matches)
                matched_keywords.extend(matches)
            
            intent_scores[intent] = (score, matched_keywords)
        
        # Find the intent with the highest score
        best_intent = max(intent_scores.keys(), key=lambda x: intent_scores[x][0])
        best_score, matched_keywords = intent_scores[best_intent]
        
        # Calculate confidence based on the score
        total_matches = sum(score for score, _ in intent_scores.values())
        confidence = best_score / total_matches if total_matches > 0 else 0.0
        
        # Extract entities
        entities = self._extract_entities(text)
        
        # Identify action items
        action_items = self._identify_action_items(text)
        
        # Perform purpose analysis
        purpose_analysis = self.purpose_analyzer.analyze_purpose(text)
        
        return IntentRecognitionResult(
            intent=best_intent,
            confidence=min(confidence, 1.0),  # Cap at 1.0
            entities=entities,
            keywords=list(set(matched_keywords)),  # Remove duplicates
            action_items=action_items,
            purpose_analysis=purpose_analysis
        )
    
    def _extract_entities(self, text: str) -> Dict[str, str]:
        """Extract named entities from the text."""
        entities = {}
        
        for entity_type, patterns in self.entity_patterns.items():
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    # Take the first match for each entity type
                    entities[entity_type] = matches[0].strip()
                    break  # Move to next entity type after first match
        
        return entities
    
    def _identify_action_items(self, text: str) -> List[str]:
        """Identify specific action items requested in the text."""
        # Look for imperative verbs and action phrases
        action_indicators = [
            r"need to (.+?)(?:\s+and|\s+but|\s+or|\.|,|$)",
            r"want to (.+?)(?:\s+and|\s+but|\s+or|\.|,|$)",
            r"would like to (.+?)(?:\s+and|\s+but|\s+or|\.|,|$)",
            r"please (.+?)(?:\s+and|\s+but|\s+or|\.|,|$)",
            r"could you (.+?)(?:\s+and|\s+but|\s+or|\.|,|$)",
            r"can you (.+?)(?:\s+and|\s+but|\s+or|\.|,|$)"
        ]
        
        actions = []
        for pattern in action_indicators:
            matches = re.findall(pattern, text, re.IGNORECASE)
            actions.extend(match.group(1).strip() for match in matches)
        
        return list(set(actions))  # Remove duplicates


from datetime import datetime
from typing import Deque
from collections import deque


@dataclass
class ConversationContext:
    """Maintains context for continuous dialogue."""
    user_id: str
    conversation_id: str
    created_at: datetime
    last_interaction: datetime
    previous_topics: List[str]
    user_preferences: Dict[str, str]
    conversation_history: Deque[str]  # Last N exchanges
    current_topic: str
    user_profile: Dict[str, str]


class NaturalLanguageProcessor:
    """
    Main processor for enhanced natural language understanding.
    
    Integrates intent recognition with other NLP capabilities to
    provide comprehensive understanding of user requirements.
    """
    
    def __init__(self):
        self.intent_recognizer = IntentRecognizer()
        self.conversation_contexts: Dict[str, ConversationContext] = {}
        self.max_history_length = 10  # Number of exchanges to remember
    
    def process_user_request(self, user_input: str, user_id: str = "default") -> IntentRecognitionResult:
        """
        Process a user request and return structured understanding.
        
        Args:
            user_input: Raw user input text
            user_id: Identifier for the user (for context management)
            
        Returns:
            Structured understanding of the user's request
        """
        # Get or create conversation context
        context = self._get_or_create_context(user_id)
        
        # Update context with current interaction
        self._update_context_with_interaction(context, user_input)
        
        # Resolve references to previous interactions if needed
        resolved_input = self._resolve_references(user_input, context)
        
        # Normalize the input
        normalized_input = self._normalize_input(resolved_input)
        
        # Recognize intent
        result = self.intent_recognizer.recognize_intent(normalized_input)
        
        return result
    
    def _get_or_create_context(self, user_id: str) -> ConversationContext:
        """Get existing context or create a new one for the user."""
        if user_id not in self.conversation_contexts:
            conversation_id = f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{user_id}"
            self.conversation_contexts[user_id] = ConversationContext(
                user_id=user_id,
                conversation_id=conversation_id,
                created_at=datetime.now(),
                last_interaction=datetime.now(),
                previous_topics=[],
                user_preferences={},
                conversation_history=deque(maxlen=self.max_history_length),
                current_topic="",
                user_profile={}
            )
        
        context = self.conversation_contexts[user_id]
        context.last_interaction = datetime.now()
        return context
    
    def _update_context_with_interaction(self, context: ConversationContext, user_input: str):
        """Update the conversation context with the new interaction."""
        # Add to conversation history
        context.conversation_history.append(user_input)
        
        # Update topics if detected
        # This is a simplified approach - in a full implementation, 
        # we would use more sophisticated topic modeling
        if len(context.previous_topics) == 0 or context.previous_topics[-1] != context.current_topic:
            # Extract potential topic from input
            potential_topic = self._extract_topic_from_input(user_input)
            if potential_topic and potential_topic != context.current_topic:
                if context.current_topic:
                    context.previous_topics.append(context.current_topic)
                context.current_topic = potential_topic
    
    def _resolve_references(self, user_input: str, context: ConversationContext) -> str:
        """
        Resolve references to previous interactions in the user input.
        
        For example, replacing "it" or "that" with the actual referenced item
        from previous exchanges.
        """
        # Look for reference words and try to resolve them
        reference_words = ["it", "that", "this", "these", "those", "the"]
        
        # Simplified reference resolution - in a full implementation,
        # this would use more sophisticated coreference resolution
        resolved_input = user_input.lower()
        
        # If the input starts with reference words, try to link to previous context
        for ref_word in reference_words:
            if resolved_input.startswith(ref_word + " ") or f" {ref_word} " in resolved_input:
                # If we have previous context, try to expand the reference
                if context.conversation_history:
                    # For simplicity, we'll just append the last exchange if it seems related
                    last_exchange = context.conversation_history[-1]
                    if len(last_exchange.split()) < 10:  # If it's a short previous exchange
                        resolved_input = f"{last_exchange} {resolved_input}"
        
        return resolved_input
    
    def _extract_topic_from_input(self, user_input: str) -> str:
        """Extract a potential topic from user input."""
        # Simple topic extraction - in a full implementation,
        # this would use more sophisticated NLP techniques
        words = user_input.split()
        # Take first few significant words as topic
        significant_words = [word for word in words if len(word) > 3 and word.isalpha()]
        return " ".join(significant_words[:3]).lower() if significant_words else ""
    
    def get_conversation_context(self, user_id: str) -> Optional[ConversationContext]:
        """Retrieve the conversation context for a user."""
        return self.conversation_contexts.get(user_id)
    
    def clear_conversation_context(self, user_id: str):
        """Clear the conversation context for a user."""
        if user_id in self.conversation_contexts:
            del self.conversation_contexts[user_id]
    
    def _normalize_input(self, text: str) -> str:
        """Normalize user input for better processing."""
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text.strip())
        
        # Expand common contractions
        contractions = {
            "don't": "do not",
            "won't": "will not", 
            "can't": "cannot",
            "n't": " not",
            "'re": " are",
            "'ve": " have",
            "'ll": " will",
            "'d": " would",
            "'m": " am"
        }
        
        for contraction, expansion in contractions.items():
            text = text.replace(contraction, expansion)
        
        return text


# Example usage and testing
if __name__ == "__main__":
    processor = NaturalLanguageProcessor()

    print("Testing basic functionality:")
    test_inputs = [
        "Can you research the latest trends in AI for me?",
        "I need to analyze the sales data from last quarter",
        "Please create a report about our customer satisfaction survey",
        "Could you automate the weekly status update emails?",
        "What is the capital of France?",
        "I want to write a blog post about renewable energy",
        "Schedule a meeting with the marketing team next week"
    ]

    for inp in test_inputs:
        result = processor.process_user_request(inp)
        print(f"Input: {inp}")
        print(f"Intent: {result.intent.value}")
        print(f"Confidence: {result.confidence:.2f}")
        print(f"Entities: {result.entities}")
        print(f"Keywords: {result.keywords}")
        print(f"Actions: {result.action_items}")
        if result.purpose_analysis:
            print(f"Primary Goal: {result.purpose_analysis.primary_goal}")
            print(f"Motivation: {result.purpose_analysis.motivation}")
            print(f"Urgency: {result.purpose_analysis.urgency_level}")
        print("-" * 50)

    print("\nTesting continuous dialogue capability:")
    user_id = "test_user_123"
    
    # Simulate a conversation
    conversation_inputs = [
        "I want to plan a trip to Paris",
        "Find flights to Paris",
        "Book a hotel in Paris",
        "What about the weather in Paris?"
    ]
    
    for inp in conversation_inputs:
        result = processor.process_user_request(inp, user_id=user_id)
        print(f"Input: {inp}")
        print(f"Intent: {result.intent.value}")
        print(f"Resolved input: {processor._resolve_references(inp, processor._get_or_create_context(user_id))}")
        print(f"Current topic: {processor.get_conversation_context(user_id).current_topic}")
        print("-" * 30)