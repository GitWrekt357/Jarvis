import os
import sys
import io
import re
import time
import wave
import array
import math

from brain import (
    Session, PERSONAS, USERS_DIR, GUESTS_DIR,
    ensure_dirs, load_json, save_json,
)

import numpy as np
from scipy.signal import resample_poly
import pyaudio
from faster_whisper import WhisperModel
from anthropic import Anthropic
from piper import PiperVoice, SynthesisConfig
from openwakeword.model import Model as WakeWordModel
from resemblyzer import VoiceEncoder, preprocess_wav
from dotenv import load_dotenv

RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 1024

SILENCE_THRESHOLD = 400
SILENCE_DURATION = 3.0
MAX_RECORD_SECONDS = 120
CONVERSATION_TIMEOUT = 25

WAKE_WORD_THRESHOLD = 0.5
WAKE_CHUNK = 1280
WAKE_WORD_MODEL_PATH = os.path.expanduser("~/desktopjarvis/wakeword_models/hey_jarvis_v0.1.onnx")

SLEEP_PHRASES = [
    "goodbye jarvis",
    "that will be all",
    "that'll be all",
    "go to sleep",
    "stop listening",
    "thanks jarvis that's all",
]

DARK_PHRASES = [
    "go dark",
    "power down completely",
    "full shutdown",
    "kill the process",
]

HOTWORDS_FILE = os.path.expanduser("~/desktopjarvis/hotwords.txt")
HOTWORD_TRIGGER = "add hotword"

PHONETIC_LETTERS = {
    "alpha": "a", "aye": "a", "bravo": "b", "bee": "b", "charlie": "c", "cee": "c", "sea": "c",
    "delta": "d", "dee": "d", "echo": "e", "foxtrot": "f", "eff": "f",
    "golf": "g", "gee": "g", "hotel": "h", "aitch": "h", "india": "i", "eye": "i",
    "juliet": "j", "jay": "j", "kilo": "k", "kay": "k", "lima": "l", "el": "l",
    "mike": "m", "em": "m", "november": "n", "en": "n", "oscar": "o", "oh": "o",
    "papa": "p", "pee": "p", "quebec": "q", "cue": "q", "queue": "q",
    "romeo": "r", "are": "r", "sierra": "s", "ess": "s", "tango": "t", "tee": "t",
    "uniform": "u", "you": "u", "victor": "v", "vee": "v", "whiskey": "w",
    "xray": "x", "ex": "x", "yankee": "y", "why": "y", "zulu": "z", "zee": "z", "zed": "z",
}

HOUSEHOLD_VOICEPRINTS_PATH = os.path.join(USERS_DIR, "household_voiceprints.json")
GUEST_VOICEPRINTS_PATH = os.path.join(GUESTS_DIR, "guest_voiceprints.json")
GUEST_PURGE_DAYS = 90

HOUSEHOLD_MATCH_THRESHOLD = 0.65
GUEST_MATCH_THRESHOLD = 0.68

NAME_FILLER_WORDS = {
    "i", "im", "am", "is", "my", "name", "call", "me", "you",
    "can", "should", "its", "it's", "the", "a", "an"
}

INPUT_DEVICE_INDEX = 13

VOICE_MODEL_PATHS = {
    "jarvis": os.path.expanduser("~/desktopjarvis/voices/en_GB-alan-medium.onnx"),
    "friday": os.path.expanduser("~/desktopjarvis/voices/en_GB-alba-medium.onnx"),
}
WHISPER_MODEL_SIZE = "small.en"

FRIDAY_TRIGGER = "switch to friday"
JARVIS_TRIGGER = "switch to jarvis"

SYN_CONFIG = SynthesisConfig(
    length_scale=0.92,
    noise_scale=0.75,
    noise_w_scale=0.85,
)


def rms(data: bytes) -> float:
    samples = array.array('h', data)
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def clean_for_speech(text: str) -> str:
    text = text.replace("\u2014", ", ").replace("\u2013", ", ")
    return text


def resample_to_model_rate(data: bytes, native_rate: int, model_rate: int) -> bytes:
    if native_rate == model_rate or not data:
        return data
    audio_np = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    gcd = math.gcd(native_rate, model_rate)
    up = model_rate // gcd
    down = native_rate // gcd
    resampled = resample_poly(audio_np, up, down)
    resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
    return resampled.tobytes()


def ensure_hotwords_file():
    if not os.path.exists(HOTWORDS_FILE):
        seed = ["Perturbator", "Carpenter Brut", "DOOM", "MF DOOM",
                "DOOMSTARKS", "DANGERDOOM", "Jarvis", "affirmative"]
        with open(HOTWORDS_FILE, "w") as f:
            f.write("\n".join(seed) + "\n")


def load_hotwords() -> list:
    if not os.path.exists(HOTWORDS_FILE):
        return []
    with open(HOTWORDS_FILE, "r") as f:
        return [line.strip() for line in f if line.strip()]


def parse_spelled_word(text: str) -> str:
    tokens = re.findall(r"[A-Za-z]+", text)
    letters = []
    for token in tokens:
        tl = token.lower()
        if len(tl) == 1:
            letters.append(tl)
        elif tl in PHONETIC_LETTERS:
            letters.append(PHONETIC_LETTERS[tl])
        else:
            letters.append(tl)
    return "".join(letters)


def add_hotword(word: str):
    existing = load_hotwords()
    if word.lower() not in [w.lower() for w in existing]:
        with open(HOTWORDS_FILE, "a") as f:
            f.write(word + "\n")


def get_embedding(encoder: VoiceEncoder, audio_bytes: bytes):
    audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    wav = preprocess_wav(audio_np, source_sr=RATE)
    return encoder.embed_utterance(wav)


def cosine_similarity(a, b) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def purge_expired_guests(guest_voiceprints: dict) -> dict:
    cutoff = time.time() - (GUEST_PURGE_DAYS * 86400)
    return {
        name: data for name, data in guest_voiceprints.items()
        if data.get("last_seen", 0) > cutoff
    }


def identify_speaker(encoder: VoiceEncoder, household_voiceprints: dict,
                      guest_voiceprints: dict, audio_bytes: bytes):
    embedding = get_embedding(encoder, audio_bytes)

    best_name, best_score = None, 0.0
    for name, stored in household_voiceprints.items():
        score = cosine_similarity(embedding, np.array(stored))
        if score > best_score:
            best_name, best_score = name, score
    if best_score >= HOUSEHOLD_MATCH_THRESHOLD:
        return best_name, "household", embedding

    best_name, best_score = None, 0.0
    for name, data in guest_voiceprints.items():
        score = cosine_similarity(embedding, np.array(data["embedding"]))
        if score > best_score:
            best_name, best_score = name, score
    if best_score >= GUEST_MATCH_THRESHOLD:
        guest_voiceprints[best_name]["last_seen"] = time.time()
        save_json(GUEST_VOICEPRINTS_PATH, guest_voiceprints)
        return best_name, "guest", embedding

    return None, None, embedding


def extract_name(text: str) -> str:
    words = re.findall(r"[A-Za-z]+", text)
    for word in words:
        if word.lower() not in NAME_FILLER_WORDS:
            return word.capitalize()
    return "Guest"


def resolve_unique_guest_name(claimed_name: str, household_voiceprints: dict, guest_voiceprints: dict) -> str:
    household_names_lower = {n.lower() for n in household_voiceprints.keys()}
    base = f"{claimed_name}_guest" if claimed_name.lower() in household_names_lower else claimed_name

    if base not in guest_voiceprints:
        return base

    counter = 2
    while f"{base}{counter}" in guest_voiceprints:
        counter += 1
    return f"{base}{counter}"


def listen_for_wake_word(p: pyaudio.PyAudio, oww_model: WakeWordModel, native_rate: int):
    wake_chunk_native = max(1, round(WAKE_CHUNK * native_rate / RATE))
    stream = p.open(
        format=FORMAT, channels=CHANNELS, rate=native_rate,
        input=True, frames_per_buffer=wake_chunk_native,
        input_device_index=INPUT_DEVICE_INDEX
    )
    print("Sleeping... say 'hey Jarvis' to wake me.")

    try:
        while True:
            audio_chunk = stream.read(wake_chunk_native, exception_on_overflow=False)
            resampled = resample_to_model_rate(audio_chunk, native_rate, RATE)
            audio_np = np.frombuffer(resampled, dtype=np.int16)
            prediction = oww_model.predict(audio_np)

            for wake_word, score in prediction.items():
                if score > WAKE_WORD_THRESHOLD:
                    print(f"Wake word detected ({wake_word}: {score:.2f})")
                    stream.stop_stream()
                    stream.close()
                    oww_model.reset()
                    return
    except KeyboardInterrupt:
        stream.stop_stream()
        stream.close()
        raise


def record_utterance(p: pyaudio.PyAudio, no_speech_timeout: float, native_rate: int):
    chunk_native = max(1, round(CHUNK * native_rate / RATE))
    stream = p.open(
        format=FORMAT, channels=CHANNELS, rate=native_rate,
        input=True, frames_per_buffer=chunk_native,
        input_device_index=INPUT_DEVICE_INDEX
    )

    print("Listening...")
    frames = []
    silence_chunks = 0
    silence_chunk_limit = int(SILENCE_DURATION * native_rate / chunk_native)
    started_talking = False
    start_time = time.time()

    while True:
        data = stream.read(chunk_native, exception_on_overflow=False)
        level = rms(data)
        elapsed = time.time() - start_time

        if level > SILENCE_THRESHOLD:
            frames.append(data)
            started_talking = True
            silence_chunks = 0
        elif started_talking:
            frames.append(data)
            silence_chunks += 1
            if silence_chunks > silence_chunk_limit:
                break
        else:
            if elapsed > no_speech_timeout:
                stream.stop_stream()
                stream.close()
                print("No speech detected, going back to sleep.")
                return None

        if elapsed > MAX_RECORD_SECONDS:
            break

    stream.stop_stream()
    stream.close()
    print("Done listening.")
    raw = b"".join(frames)
    return resample_to_model_rate(raw, native_rate, RATE)


def transcribe(whisper_model: WhisperModel, audio_bytes: bytes) -> str:
    audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    current_hotwords = load_hotwords()
    segments, _ = whisper_model.transcribe(
        audio_np,
        language="en",
        condition_on_previous_text=False,
        vad_filter=True,
        hotwords=" ".join(current_hotwords) if current_hotwords else None,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


def speak(voice: PiperVoice, p: pyaudio.PyAudio, text: str):
    text = clean_for_speech(text)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file, syn_config=SYN_CONFIG)
    buffer.seek(0)

    with wave.open(buffer, "rb") as wav_file:
        out_stream = p.open(
            format=p.get_format_from_width(wav_file.getsampwidth()),
            channels=wav_file.getnchannels(),
            rate=wav_file.getframerate(),
            output=True
        )
        data = wav_file.readframes(CHUNK)
        while data:
            out_stream.write(data)
            data = wav_file.readframes(CHUNK)
        out_stream.stop_stream()
        out_stream.close()


def main():
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is missing!")
        sys.exit(1)

    ensure_dirs()
    ensure_hotwords_file()
    household_voiceprints = load_json(HOUSEHOLD_VOICEPRINTS_PATH)
    guest_voiceprints = load_json(GUEST_VOICEPRINTS_PATH)

    before_count = len(guest_voiceprints)
    guest_voiceprints = purge_expired_guests(guest_voiceprints)
    if len(guest_voiceprints) != before_count:
        save_json(GUEST_VOICEPRINTS_PATH, guest_voiceprints)
        print(f"Purged {before_count - len(guest_voiceprints)} expired guest voiceprint(s).")

    p = pyaudio.PyAudio()

    if INPUT_DEVICE_INDEX is None:
        print("Available input devices (set INPUT_DEVICE_INDEX to the right one):")
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info['maxInputChannels'] > 0:
                print(f"   [{i}] {info['name']}")
        print()
        native_rate = RATE
    else:
        device_info = p.get_device_info_by_index(INPUT_DEVICE_INDEX)
        native_rate = int(device_info['defaultSampleRate'])
        print(f"Recording at native device rate: {native_rate} Hz (resampled to {RATE} Hz for processing)")

    print("Loading wake word model...")
    oww_model = WakeWordModel(wakeword_model_paths=[WAKE_WORD_MODEL_PATH])

    print("Loading voice recognition model...")
    voice_encoder = VoiceEncoder()

    print("Loading Whisper model...")
    whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")

    print("Loading Piper voices...")
    voices = {
        key: PiperVoice.load(path) for key, path in VOICE_MODEL_PATHS.items()
    }

    print("Connecting to Claude API...")
    client = Anthropic(api_key=api_key)

    print("Jarvis is online. Say 'hey Jarvis' to start a conversation. Press Ctrl+C to exit.")

    try:
        while True:
            listen_for_wake_word(p, oww_model, native_rate)
            speak(voices["jarvis"], p, "Yes, how may I help you?")

            first_audio = record_utterance(p, no_speech_timeout=CONVERSATION_TIMEOUT, native_rate=native_rate)
            if first_audio is None or len(first_audio) < RATE // 2:
                continue

            speaker_name, tier, embedding = identify_speaker(
                voice_encoder, household_voiceprints, guest_voiceprints, first_audio
            )

            if speaker_name is None:
                speak(voices["jarvis"], p, "I don't recognize your voice yet. Just tell me your first name.")
                name_audio = record_utterance(p, no_speech_timeout=15, native_rate=native_rate)
                if name_audio is None or len(name_audio) < RATE // 4:
                    speak(voices["jarvis"], p, "I didn't catch that. We'll try again next time.")
                    continue

                name_text = transcribe(whisper_model, name_audio)
                claimed_name = extract_name(name_text)
                speaker_name = resolve_unique_guest_name(claimed_name, household_voiceprints, guest_voiceprints)

                guest_voiceprints[speaker_name] = {
                    "embedding": embedding.tolist(),
                    "last_seen": time.time()
                }
                save_json(GUEST_VOICEPRINTS_PATH, guest_voiceprints)
                tier = "guest"

                if speaker_name != claimed_name:
                    speak(voices["jarvis"], p, f"That name is already taken by someone I trust or already know. I'll call you {speaker_name} instead.")
                speak(voices["jarvis"], p, f"Nice to meet you, {speaker_name}. What can I help you with?")
                first_audio = None

            # The shared brain handles memory summary, context loading, and the system prompt.
            session = Session(client, speaker_name, tier, persona="jarvis", device="desktop")
            active_voice = voices[PERSONAS[session.persona]["voice"]]

            in_conversation = True
            pending_audio = first_audio

            while in_conversation:
                audio_bytes = pending_audio if pending_audio is not None else record_utterance(
                    p, no_speech_timeout=CONVERSATION_TIMEOUT, native_rate=native_rate
                )
                pending_audio = None

                if audio_bytes is None:
                    speak(active_voice, p, "Now sleeping.")
                    in_conversation = False
                    break

                if len(audio_bytes) < RATE // 2:
                    continue

                print("Transcribing...")
                user_text = transcribe(whisper_model, audio_bytes)

                if not user_text:
                    print("Didn't catch anything, listening again...")
                    continue

                print(f"{speaker_name} ({tier}) said: {user_text}")

                lower_text = user_text.lower()

                if any(phrase in lower_text for phrase in DARK_PHRASES):
                    speak(active_voice, p, "Are you sure you want me to power down completely? Say affirmative to confirm.")
                    confirm_audio = record_utterance(p, no_speech_timeout=15, native_rate=native_rate)
                    confirmed = confirm_audio is not None and len(confirm_audio) >= RATE // 2 and \
                        "affirmative" in transcribe(whisper_model, confirm_audio).lower()
                    if confirmed:
                        speak(active_voice, p, "Going dark. Goodbye.")
                        sys.exit(0)
                    else:
                        speak(active_voice, p, "Understood. I will remain online.")
                        continue

                if any(phrase in lower_text for phrase in SLEEP_PHRASES):
                    speak(active_voice, p, "Very good, sir. I will be here if you need me.")
                    in_conversation = False
                    break

                if FRIDAY_TRIGGER in lower_text and session.persona != "friday":
                    speak(active_voice, p, "Right, handing off to Friday now.")
                    session.set_persona("friday")
                    active_voice = voices[PERSONAS[session.persona]["voice"]]
                    continue

                if JARVIS_TRIGGER in lower_text and session.persona != "jarvis":
                    speak(active_voice, p, "Switching back to Jarvis.")
                    session.set_persona("jarvis")
                    active_voice = voices[PERSONAS[session.persona]["voice"]]
                    continue

                if HOTWORD_TRIGGER in lower_text:
                    spelled_part = re.sub(HOTWORD_TRIGGER, "", user_text, flags=re.IGNORECASE).strip(" ,.")
                    new_word = parse_spelled_word(spelled_part)
                    if new_word:
                        add_hotword(new_word)
                        speak(active_voice, p, f"Got it. I've added {new_word}, spelled {' '.join(new_word.upper())}, to my hotword list.")
                    else:
                        speak(active_voice, p, "I didn't catch a word to add. Try spelling it again.")
                    continue

                text_for_claude, notice = session.route(user_text)
                if notice:
                    speak(active_voice, p, notice)

                print("Thinking...")
                reply_text = session.ask(text_for_claude)
                print(f"{session.persona.title()}: {reply_text}")

                speak(active_voice, p, reply_text)

    except KeyboardInterrupt:
        print("\nShutting down Jarvis session cleanly...")
    finally:
        p.terminate()


if __name__ == "__main__":
    main()
