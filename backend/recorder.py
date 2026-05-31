import sounddevice as sd
from scipy.io.wavfile import write
import numpy as np


def record_audio(filename="command.wav", duration=8, sample_rate=16000):
    print("Available microphones:")
    print(sd.query_devices())

    print("Recording... speak clearly now.")

    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
    )

    sd.wait()

    # Normalize volume so Whisper gets louder/clearer audio
    max_value = np.max(np.abs(audio))
    if max_value > 0:
        audio = audio / max_value * 0.9

    # Convert to int16 WAV
    audio_int16 = (audio * 32767).astype(np.int16)

    write(filename, sample_rate, audio_int16)

    print(f"Saved recording to {filename}")
    return filename