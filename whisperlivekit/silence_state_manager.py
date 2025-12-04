"""
Silence state management system to handle transcription during silence periods.
"""
import logging
from typing import List, Optional
from time import time
from whisperlivekit.timed_objects import ASRToken

logger = logging.getLogger(__name__)


class SilenceStateManager:
    """
    Manages transcription state during silence periods to prevent word repetition.
    
    Handles transitions between silence and speech, manages pending tokens,
    and ensures proper state cleanup during silence periods.
    """
    
    def __init__(self):
        """Initialize the silence state manager."""
        self.is_in_silence: bool = False
        self.silence_start_time: Optional[float] = None
        self.pending_tokens: List[ASRToken] = []
        self.last_speech_end_time: Optional[float] = None
        
    def enter_silence(self, timestamp: float) -> List[ASRToken]:
        """
        Handle transition to silence state.
        
        Args:
            timestamp: Time when silence started
            
        Returns:
            List of tokens to finalize before entering silence
        """
        if self.is_in_silence:
            return []
            
        logger.debug(f"Entering silence at {timestamp:.2f}s")
        self.is_in_silence = True
        self.silence_start_time = timestamp
        
        # Finalize any pending tokens
        finalized_tokens = self.pending_tokens.copy()
        self.pending_tokens.clear()
        
        return finalized_tokens
        
    def exit_silence(self, timestamp: float) -> None:
        """
        Handle transition from silence to speech.
        
        Args:
            timestamp: Time when speech resumed
        """
        if not self.is_in_silence:
            return
            
        silence_duration = timestamp - (self.silence_start_time or timestamp)
        logger.debug(f"Exiting silence at {timestamp:.2f}s (duration: {silence_duration:.2f}s)")
        
        self.is_in_silence = False
        self.last_speech_end_time = timestamp
        self.silence_start_time = None
        
    def should_process_transcription(self) -> bool:
        """
        Determine if transcription should be processed based on silence state.
        
        Returns:
            True if transcription should be processed
        """
        return not self.is_in_silence
        
    def add_pending_token(self, token: ASRToken) -> None:
        """
        Add a token to pending list during silence processing.
        
        Args:
            token: Token to add to pending list
        """
        self.pending_tokens.append(token)
        
    def get_silence_duration(self) -> float:
        """
        Get current silence duration.
        
        Returns:
            Duration of current silence period in seconds
        """
        if not self.is_in_silence or not self.silence_start_time:
            return 0.0
        return time() - self.silence_start_time
        
    def reset_state(self) -> None:
        """Reset all silence state."""
        logger.debug("Resetting silence state")
        self.is_in_silence = False
        self.silence_start_time = None
        self.pending_tokens.clear()
        self.last_speech_end_time = None