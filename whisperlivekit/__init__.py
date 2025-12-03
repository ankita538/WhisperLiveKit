from .audio_processor import AudioProcessor
from .core import TranscriptionEngine
from .parse_args import parse_args
from .web.web_interface import get_web_interface_html, get_inline_ui_html

# Optional: import the web app if available
try:
    from .basic_server import app
except Exception:
    app = None

# Optional: import helper to download simulstreaming backend if available
# (original __all__ referenced this name but didn't show an import)
try:
    from .backends import download_simulstreaming_backend
except Exception:
    download_simulstreaming_backend = None

__version__ = "0.1.0"

__all__ = [
    "TranscriptionEngine",
    "AudioProcessor",
    "parse_args",
    "get_web_interface_html",
    "get_inline_ui_html",
    "download_simulstreaming_backend",
    "app",
    "__version__",
]