"""
Token deduplication system to prevent repetitive words in transcription output.
"""
import logging
from typing import List, Optional, Dict, Any
from whisperlivekit.timed_objects import ASRToken

logger = logging.getLogger(__name__)


class TokenDeduplicator:
    """
    Prevents duplicate tokens from being output to the transcription stream.
    
    Uses token history and similarity comparison to detect and prevent duplicates
    that can occur during silence periods or buffer processing issues.
    """
    
    def __init__(self, history_size: int = 50, similarity_threshold: float = 0.9):
        """
        Initialize the token deduplicator.
        
        Args:
            history_size: Maximum number of tokens to keep in history
            similarity_threshold: Threshold for considering tokens similar (0.0-1.0)
        """
        self.token_history: List[ASRToken] = []
        self.history_size = history_size
        self.similarity_threshold = similarity_threshold
        self.last_token_time = 0.0
        
    def is_duplicate(self, token: ASRToken) -> bool:
        """
        Check if a token is a duplicate of recent history.
        
        Args:
            token: Token to check for duplication
            
        Returns:
            True if token is considered a duplicate
        """
        if not self.token_history:
            return False
            
        # Check for exact text matches in recent history
        recent_texts = [t.text for t in self.token_history[-10:]]  # Check last 10 tokens
        
        # Exact match check
        if token.text in recent_texts:
            # Additional check: if the token time is very close to a previous token
            # with the same text, it's likely a duplicate
            for hist_token in reversed(self.token_history[-10:]):
                if (hist_token.text == token.text and 
                    abs(hist_token.start - token.start) < 0.5):  # Within 500ms
                    logger.debug(f"Detected duplicate token: '{token.text}' at {token.start:.2f}s")
                    return True
                    
        return False
        
    def add_validated_token(self, token: ASRToken) -> None:
        """
        Add a validated token to the history.
        
        Args:
            token: Token that has been validated and output
        """
        self.token_history.append(token)
        self.last_token_time = token.end
        
        # Trim history if it exceeds size limit
        if len(self.token_history) > self.history_size:
            self.token_history = self.token_history[-self.history_size:]
            
    def clear_history(self) -> None:
        """Clear token history during silence transitions."""
        logger.debug("Clearing token deduplication history")
        self.token_history.clear()
        self.last_token_time = 0.0
        
    def get_stats(self) -> Dict[str, Any]:
        """Get deduplication statistics for monitoring."""
        return {
            "history_size": len(self.token_history),
            "last_token_time": self.last_token_time,
            "recent_tokens": [t.text for t in self.token_history[-5:]]
        }