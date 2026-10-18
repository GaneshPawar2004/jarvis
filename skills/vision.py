"""Vision skills: look through the webcam or at the screen and answer questions about it.
Images stay on this PC except for the one sent to Gemini for each question."""
import re

import cv2
import mss
import numpy as np
from google.genai import types

import config
from core import llm

VISION_DIR = config.DATA_DIR / "vision"
FACES_DIR = config.DATA_DIR / "faces"
MAX_SIDE = 1600


def _jpeg(image: np.ndarray) -> bytes:
    h, w = image.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("Could not encode the image.")
    return data.tobytes()


def _capture_webcam() -> np.ndarray:
    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    try:
        if not camera.isOpened():
            raise RuntimeError("No webcam found, or another app is using it.")
        frame = None
        for _ in range(15):  # let auto-exposure settle
            ok, frame = camera.read()
        if frame is None or not ok:
            raise RuntimeError("The webcam returned no image.")
        return frame
    finally:
        camera.release()


def _capture_screen() -> np.ndarray:
    with mss.mss() as screen:
        shot = np.array(screen.grab(screen.monitors[1]))
    return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)


def _ask_gemini(parts: list[types.Part]) -> str:
    response, _ = llm.generate([types.Content(role="user", parts=parts)])
    return (response.text or "").strip() or "I couldn't make anything out."


def _image_part(image: np.ndarray) -> types.Part:
    return types.Part.from_bytes(data=_jpeg(image), mime_type="image/jpeg")


def look_through_webcam(question: str) -> str:
    """Take a photo with the webcam and answer a question about what it shows (the user,
    objects they hold up, the room, who is there). Only use this when the user asks you to
    look, see or check the camera.

    Args:
        question: What to find out from the photo, e.g. "What is the user holding?" or "Describe what you see."
    """
    frame = _capture_webcam()
    VISION_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(VISION_DIR / "last_webcam.jpg"), frame)

    parts: list[types.Part] = []
    faces = sorted(FACES_DIR.glob("*.jpg")) if FACES_DIR.exists() else []
    for face in faces:
        parts += [types.Part(text=f"Reference photo of {face.stem}:"), _image_part(cv2.imread(str(face)))]
    known = ", ".join(f.stem for f in faces)
    instructions = (
        "This is a live webcam photo from the user's computer. Answer the question briefly and "
        "concretely, in plain sentences without markdown."
        + (f" If anyone in it matches a reference photo ({known}), name them; otherwise don't guess names." if faces else "")
    )
    parts += [types.Part(text="Webcam photo:"), _image_part(frame), types.Part(text=f"{instructions}\n\nQuestion: {question}")]
    return _ask_gemini(parts)


def look_at_screen(question: str) -> str:
    """Look at what is currently on the user's screen and answer a question about it
    (read an error message, summarise a page, explain what's open, help with what they're doing).

    Args:
        question: What to find out from the screen, e.g. "What does this error mean?"
    """
    parts = [
        _image_part(_capture_screen()),
        types.Part(text=f"This is a screenshot of the user's computer screen. Answer briefly, in plain "
                        f"sentences without markdown.\n\nQuestion: {question}"),
    ]
    return _ask_gemini(parts)


def remember_face(name: str) -> str:
    """Take a webcam photo of the person in front of the camera and save it so they can be
    recognised later. Only use this when the user explicitly asks you to remember a face.

    Args:
        name: The person's name, e.g. "Nikhil".
    """
    safe = re.sub(r"[^\w\- ]", "", name).strip()
    if not safe:
        return "Please give a valid name."
    frame = _capture_webcam()
    FACES_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(FACES_DIR / f"{safe}.jpg"), frame)
    return f"Saved a reference photo of {safe}. I'll recognise them when I look through the webcam."


def forget_face(name: str) -> str:
    """Delete a saved reference photo so that person is no longer recognised.

    Args:
        name: The person's name.
    """
    path = FACES_DIR / f"{re.sub(r'[^\w\- ]', '', name).strip()}.jpg"
    if not path.exists():
        return f"No saved face called {name}."
    path.unlink()
    return f"Deleted the saved face of {name}."
