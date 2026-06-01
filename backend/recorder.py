import sounddevice as sd
from scipy.io.wavfile import write
import numpy as np
from pathlib import Path
from tempfile import gettempdir


def record_audio(filename="command.wav", duration=4, sample_rate=16000):
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

    output_path = Path(filename)

    if not output_path.is_absolute():
        output_path = Path(gettempdir()) / output_path

    write(str(output_path), sample_rate, audio_int16)

    print(f"Saved recording to {output_path}")
    return str(output_path)
