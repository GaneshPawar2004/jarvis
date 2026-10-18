"""Wake-word voice interface for JARVIS."""
import asyncio
import tempfile
import time
import wave
import winsound
from collections import deque
from pathlib import Path

import av
import edge_tts
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
import openwakeword
from openwakeword.model import Model
from playsound3 import playsound
from rich.console import Console

import config
from core.brain import Brain

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 1_280  # 80 ms, the frame size openWakeWord expects
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE
WAKE_THRESHOLD = 0.5
VOICE = "en-GB-RyanNeural"

SPEECH_FACTOR = 4.0  # speech must be this many times louder than background noise
MIN_SPEECH_RMS = 150
START_TIMEOUT = 5.0  # seconds to start speaking after the wake word
MAX_COMMAND = 12.0  # longest single request
END_SILENCE = 1.0  # pause that ends a request
PRE_ROLL_FRAMES = 4  # keep ~0.3 s before speech so the first word isn't clipped

ACK_FILE = config.DATA_DIR / "voice_cache" / "yes_sir.wav"
console = Console()


def _rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))


def _drain(stream: sd.InputStream) -> None:
    """Throw away audio buffered while JARVIS was busy, so it isn't processed late."""
    available = stream.read_available
    if available:
        stream.read(available)


class NoiseFloor:
    """Tracks background noise so speech detection adapts to the mic and the room."""

    def __init__(self, stream: sd.InputStream, seconds: float = 1.0):
        frames = [stream.read(FRAME_SAMPLES)[0][:, 0] for _ in range(int(seconds / FRAME_SECONDS))]
        self.level = float(np.median([_rms(f) for f in frames]))

    def update(self, rms: float) -> None:
        self.level = 0.98 * self.level + 0.02 * rms

    @property
    def speech_threshold(self) -> float:
        return max(self.level * SPEECH_FACTOR, MIN_SPEECH_RMS)


def _listen_for_command(stream: sd.InputStream, noise: NoiseFloor) -> np.ndarray | None:
    """Record one request: wait for speech, then stop after a short pause."""
    threshold = noise.speech_threshold
    pre_roll = deque(maxlen=PRE_ROLL_FRAMES)
    chunks: list[np.ndarray] = []
    started = time.monotonic()
    speech_started = None
    silence_started = None

    while True:
        now = time.monotonic()
        if speech_started is None and now - started > START_TIMEOUT:
            return None
        if speech_started is not None and now - speech_started > MAX_COMMAND:
            break

        frame = stream.read(FRAME_SAMPLES)[0][:, 0].copy()
        loud = _rms(frame) > threshold

        if speech_started is None:
            pre_roll.append(frame)
            if loud:
                speech_started = now
                chunks.extend(pre_roll)
            continue

        chunks.append(frame)
        if loud:
            silence_started = None
        else:
            silence_started = silence_started or now
            if now - silence_started > END_SILENCE:
                break

    return np.concatenate(chunks).astype(np.float32) / 32768.0


def _transcribe(model: WhisperModel, audio: np.ndarray) -> str:
    segments, _ = model.transcribe(audio, language="en", vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()


async def _synthesize(text: str, path: Path) -> None:
    await edge_tts.Communicate(text, VOICE).save(str(path))


def _speak(text: str) -> bool:
    """Speak a reply with a British English voice. Returns False if speech is unavailable."""
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as audio_file:
            path = Path(audio_file.name)
        asyncio.run(_synthesize(text, path))
        playsound(str(path))
        return True
    except Exception:
        return False
    finally:
        if path:
            path.unlink(missing_ok=True)


def _mp3_to_wav(src: Path, dst: Path) -> None:
    """Decode to 16-bit mono WAV, which Windows can play with no start-up delay."""
    with av.open(str(src)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=24_000)
        samples = np.concatenate([
            out.to_ndarray().ravel()
            for frame in container.decode(audio=0)
            for out in resampler.resample(frame)
        ])
    voiced = np.flatnonzero(np.abs(samples) > 500)  # trim the TTS's silent padding
    if voiced.size:
        pad = 1_200  # 50 ms
        samples = samples[max(voiced[0] - pad, 0): voiced[-1] + pad]
    with wave.open(str(dst), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24_000)
        wav.writeframes(samples.astype(np.int16).tobytes())


def _prepare_ack() -> bool:
    """Cache the spoken "Yes, sir?" so the wake response plays instantly."""
    if ACK_FILE.exists():
        return True
    mp3 = ACK_FILE.with_suffix(".mp3")
    try:
        ACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(_synthesize(f"Yes, {config.USER_NAME}?", mp3))
        _mp3_to_wav(mp3, ACK_FILE)
        return True
    except Exception:
        ACK_FILE.unlink(missing_ok=True)
        return False
    finally:
        mp3.unlink(missing_ok=True)


def _acknowledge(has_ack: bool) -> None:
    if has_ack:
        try:
            winsound.PlaySound(str(ACK_FILE), winsound.SND_FILENAME)
            return
        except Exception:
            pass
    winsound.Beep(880, 150)


def _show_tool(name: str, args: dict) -> None:
    detail = ", ".join(f"{k}={v!r}" for k, v in args.items())
    console.print(f"  [dim cyan]⚙ {name}({detail})[/]")


def run() -> None:
    """Listen for 'Hey Jarvis', then handle a spoken request."""
    console.print("[cyan]JARVIS voice is starting. Press Ctrl+C to stop.[/]")
    console.print("[dim]The first start downloads the local wake-word and English speech models.[/]")
    openwakeword.utils.download_models(["hey_jarvis"])
    wakeword = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    recognizer = WhisperModel("base.en", device="cpu", compute_type="int8")
    brain = Brain(on_tool=_show_tool)
    has_ack = _prepare_ack()
    speech_warned = False

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME_SAMPLES) as stream:
            console.print("[dim]Measuring background noise, please stay quiet for a second…[/]")
            noise = NoiseFloor(stream)
            console.print(f"[bold cyan]Ready.[/] Say [bold]'Hey Jarvis'[/]. [dim](noise level {noise.level:.0f})[/]")

            while True:
                frame = stream.read(FRAME_SAMPLES)[0][:, 0]
                predictions = wakeword.predict(frame)
                if max(predictions.values(), default=0) < WAKE_THRESHOLD:
                    noise.update(_rms(frame))
                    continue

                _acknowledge(has_ack)
                _drain(stream)  # don't record the acknowledgement itself
                console.print("[bold cyan]JARVIS:[/] Listening…")
                audio = _listen_for_command(stream, noise)

                if audio is None:
                    console.print("[dim]I didn't hear a request.[/]")
                else:
                    text = _transcribe(recognizer, audio)
                    if not text:
                        console.print(f"[dim]I couldn't make that out, {config.USER_NAME}.[/]")
                    else:
                        console.print(f"[yellow]You:[/] {text}")
                        try:
                            reply = brain.ask(text)
                        except Exception as error:
                            reply = None
                            console.print(f"[bold red]Error:[/] {error}")
                        if reply:
                            console.print(f"[bold cyan]JARVIS:[/] {reply}  [dim]({brain.active_model})[/]")
                            if not _speak(reply) and not speech_warned:
                                console.print("[yellow]Speech is unavailable (no internet connection?). Replies will be shown as text.[/]")
                                speech_warned = True

                _drain(stream)
                wakeword.reset()
                console.print("[dim]Say 'Hey Jarvis' when you need me.[/]")
    except KeyboardInterrupt:
        console.print("\n[cyan]Saving memories…[/]")
        brain.close()
        console.print("[cyan]Voice interface stopped.[/]")
