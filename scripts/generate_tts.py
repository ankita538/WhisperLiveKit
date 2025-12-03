import pyttsx3
from pathlib import Path

out = Path(__file__).parent / "sample_tts.wav"
text = "This is a short test sentence for WhisperLiveKit. Hello from the test script."

engine = pyttsx3.init()
# Optionally adjust voice rate and volume
engine.setProperty("rate", 150)
engine.setProperty("volume", 1.0)

print(f"Generating TTS WAV at: {out}")
engine.save_to_file(text, str(out))
engine.runAndWait()
print("WAV generation complete.")
