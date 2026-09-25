import os
import sys
import math
import json
import numpy as np
import pyaudio
from scipy.signal import resample_poly
from resemblyzer import VoiceEncoder, preprocess_wav

RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16
RECORD_SECONDS = 5
INPUT_DEVICE_INDEX = 13

HOUSEHOLD_VOICEPRINTS_PATH = os.path.expanduser("~/desktopjarvis/users/household_voiceprints.json")

PHRASES = [
    "Hey Jarvis, what's on my calendar today?",
    "Hey Jarvis, remind me to feed the dogs before six.",
    "The quick brown fox jumps over the lazy dog near the old wooden fence.",
    "Could you remind me what time the meeting starts tomorrow afternoon?",
    "Hey Jarvis, go dark.",
]

STYLES = [
    "in your normal, everyday voice",
    "like you're excited to see an old friend you haven't seen in ages",
    "like you're exhausted and can barely be bothered to talk right now",
]


def resample_to_16k(data: bytes, native_rate: int) -> bytes:
    if native_rate == RATE or not data:
        return data
    audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    gcd = math.gcd(native_rate, RATE)
    up = RATE // gcd
    down = native_rate // gcd
    resampled = resample_poly(audio_np, up, down)
    resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
    return resampled.tobytes()


def record_fixed(p: pyaudio.PyAudio, seconds: float, native_rate: int) -> bytes:
    chunk = 1024
    stream = p.open(
        format=FORMAT, channels=CHANNELS, rate=native_rate,
        input=True, frames_per_buffer=chunk,
        input_device_index=INPUT_DEVICE_INDEX
    )
    frames = []
    for _ in range(int(native_rate / chunk * seconds)):
        frames.append(stream.read(chunk, exception_on_overflow=False))
    stream.stop_stream()
    stream.close()
    raw = b"".join(frames)
    return resample_to_16k(raw, native_rate)


def cosine_similarity(a, b) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def capture_sample(p, encoder, native_rate, prompt_text, style_text, sample_num, total_samples):
    input(
        f"Sample {sample_num}/{total_samples} -- press Enter, then say {style_text}:\n"
        f"  \"{prompt_text}\"\n"
    )
    print(f"Recording for {RECORD_SECONDS} seconds...")
    audio_bytes = record_fixed(p, RECORD_SECONDS, native_rate)
    audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    wav = preprocess_wav(audio_np, source_sr=RATE)
    embedding = encoder.embed_utterance(wav)
    print("Captured.\n")
    return embedding


def main():
    if len(sys.argv) < 2:
        print("Usage: python enroll_household.py <Name>")
        sys.exit(1)
    name = sys.argv[1].strip().capitalize()

    p = pyaudio.PyAudio()
    device_info = p.get_device_info_by_index(INPUT_DEVICE_INDEX)
    native_rate = int(device_info['defaultSampleRate'])

    print("Loading voice recognition model...")
    encoder = VoiceEncoder()

    total_samples = len(PHRASES) * len(STYLES)
    print(f"\nEnrolling '{name}' as a trusted household member.")
    print(f"You'll say {len(PHRASES)} phrases, each in {len(STYLES)} different deliveries "
          f"({total_samples} recordings total).")
    print("This deliberately captures your natural vocal range, not just one register.\n")

    embeddings = []
    sample_num = 1
    for phrase in PHRASES:
        for style in STYLES:
            embedding = capture_sample(p, encoder, native_rate, phrase, style, sample_num, total_samples)
            embeddings.append(embedding)
            sample_num += 1

    p.terminate()

    n = len(embeddings)
    pairwise_scores = []
    for i in range(n):
        for j in range(i + 1, n):
            pairwise_scores.append(cosine_similarity(embeddings[i], embeddings[j]))

    min_score = min(pairwise_scores)
    avg_score = sum(pairwise_scores) / len(pairwise_scores)
    print(f"Sample self-consistency -- average: {avg_score:.4f}, minimum: {min_score:.4f}")
    if min_score < 0.5:
        print("Warning: at least one sample looks like a real outlier (very low similarity to")
        print("the others) -- more than expected from deliberate delivery variation alone.")
        print("This can happen from background noise or a mic issue on that specific take.\n")
    else:
        print("All samples stayed reasonably consistent despite the deliberate delivery variety --")
        print("that's a good sign the model is tracking your voice, not just your mood.\n")

    avg_embedding = np.mean(embeddings, axis=0)
    avg_embedding = avg_embedding / np.linalg.norm(avg_embedding)

    if os.path.exists(HOUSEHOLD_VOICEPRINTS_PATH):
        with open(HOUSEHOLD_VOICEPRINTS_PATH, "r") as f:
            household_voiceprints = json.load(f)
    else:
        household_voiceprints = {}

    household_voiceprints[name] = avg_embedding.tolist()

    with open(HOUSEHOLD_VOICEPRINTS_PATH, "w") as f:
        json.dump(household_voiceprints, f)

    print(f"Enrolled '{name}' as a trusted household member using {n} averaged samples.")
    print(f"Saved to {HOUSEHOLD_VOICEPRINTS_PATH}")


if __name__ == "__main__":
    main()
