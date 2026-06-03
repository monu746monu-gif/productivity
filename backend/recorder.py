import sounddevice as sd
from scipy.io.wavfile import write
import numpy as np
from pathlib import Path
from tempfile import gettempdir


def record_audio(filename="command.wav", duration=4, sample_rate=16000):
    print("Recording... speak clearly now.")

    chunk_seconds = 0.1
    chunk_size = int(sample_rate * chunk_seconds)
    min_duration = min(1.8, duration)
    silence_duration = 0.9
    speech_threshold = 0.018
    chunks = []
    heard_speech = False
    silent_for = 0.0
    recorded_for = 0.0

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=chunk_size,
    ) as stream:
        while recorded_for < duration:
            chunk, _overflowed = stream.read(chunk_size)
            chunks.append(chunk.copy())
            recorded_for += chunk_seconds

            volume = float(np.sqrt(np.mean(np.square(chunk))))

            if volume > speech_threshold:
                heard_speech = True
                silent_for = 0.0
            elif heard_speech and recorded_for >= min_duration:
                silent_for += chunk_seconds

                if silent_for >= silence_duration:
                    break

    audio = np.concatenate(chunks) if chunks else np.zeros((1, 1), dtype="float32")

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
