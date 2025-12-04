"""
Token processing state management for deduplication and silence handling.
"""
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any
from whisperlivekit.token_deduplicator import TokenDeduplicator
from whisperlivekit.silence_state_manager import SilenceStateManager

logger = logging.getLogger(__name__)


@dataclass
class TokenProcessingState:
    """
    Manages the overall state for token processing, deduplication, and silence handling.
    """
    
    last_output_time: float = 0.0
    last_token_id: Optional[str] = None
    silence_state: Optional[SilenceStateManager] = None
    deduplicator: Optional[TokenDeduplicator] = None
    buffer_validation_state: Dict[str, Any] = None
    
    def __post_init__(self):
        """Initialize components after dataclass creation."""
        if self.silence_state is None:
            self.silence_state = SilenceStateManager()
        if self.deduplicator is None:
            self.deduplicator = TokenDeduplicator()
        if self.buffer_validation_state is None:
            self.buffer_validation_state = {}
            
    def reset_state(self) -> None:
        """Reset all processing state."""
        logger.info("Resetting token processing state")
        self.last_output_time = 0.0
        self.last_token_id = None
        self.silence_state.reset_state()
        self.deduplicator.clear_history()
        self.buffer_validation_state.clear()
        
    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics for monitoring."""
        return {
            "last_output_time": self.last_output_time,
            "last_token_id": self.last_token_id,
            "silence_duration": self.silence_state.get_silence_duration(),
            "is_in_silence": self.silence_state.is_in_silence,
            "deduplicator_stats": self.deduplicator.get_stats()
        }