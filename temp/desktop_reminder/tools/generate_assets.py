"""Generates the bundled sample assets (pure standard library, no Pillow needed):

  assets/sounds/{enter,happy,angry,reminder,exit}.wav   simple synthesized effects
  assets/characters/robot/                              a manifest-only PNG-sequence character

Run:  python tools/generate_assets.py
"""
import json
import math
import struct
import wave
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATE = 22050


# ------------------------------------------------------------------ sounds
def tone(freq, ms, vol=0.35, shape="sine"):
    n = int(RATE * ms / 1000)
    out = []
    for i in range(n):
        phase = 2 * math.pi * freq * i / RATE
        v = math.sin(phase) if shape == "sine" else (1.0 if math.sin(phase) >= 0 else -1.0)
        env = min(1.0, i / (RATE * 0.01)) * min(1.0, (n - i) / (RATE * 0.04))
        out.append(int(32767 * vol * env * v))
    return out


def write_wav(path, samples):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", s) for s in samples))


def make_sounds():
    d = ROOT / "assets" / "sounds"
    write_wav(d / "enter.wav", tone(330, 90) + tone(440, 90) + tone(550, 120))
    write_wav(d / "reminder.wav", tone(880, 160) + tone(1320, 300, 0.3))
    write_wav(d / "happy.wav", tone(523, 90) + tone(659, 90) + tone(784, 90) + tone(1047, 220))
    write_wav(d / "angry.wav", tone(130, 200, 0.3, "square") + tone(100, 300, 0.3, "square"))
    write_wav(d / "exit.wav", tone(550, 90) + tone(440, 90) + tone(330, 140))


# ------------------------------------------------------------------ robot art
class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = bytearray(w * h * 4)

    def rect(self, x, y, w, h, colour):
        r, g, b, a = colour
        for yy in range(max(0, y), min(self.h, y + h)):
            for xx in range(max(0, x), min(self.w, x + w)):
                i = (yy * self.w + xx) * 4
                self.px[i:i + 4] = bytes((r, g, b, a))

    def png(self):
        raw = b"".join(b"\x00" + bytes(self.px[y * self.w * 4:(y + 1) * self.w * 4])
                       for y in range(self.h))

        def chunk(kind, data):
            return (struct.pack(">I", len(data)) + kind + data
                    + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


METAL, DARK, WHITE = (150, 165, 185, 255), (50, 60, 75, 255), (255, 255, 255, 255)


def robot(leg=0, eye=(80, 220, 255, 255), arms_up=False, bob=0, antenna=True, shake=0):
    c = Canvas(96, 96)
    x0, y0 = 20 + shake, 8 + bob
    c.rect(x0 + 18, y0 + 66 + leg, 12, 18 - leg, DARK)               # legs
    c.rect(x0 + 38, y0 + 66 - leg, 12, 18 + leg, DARK)
    c.rect(x0 + 8, y0 + 34, 52, 34, METAL)                            # torso
    c.rect(x0 + 14, y0 + 6, 40, 30, METAL)                            # head
    c.rect(x0 + 20, y0 + 14, 10, 10, eye)                             # eyes
    c.rect(x0 + 38, y0 + 14, 10, 10, eye)
    c.rect(x0 + 22, y0 + 28, 24, 3, DARK)                             # mouth slot
    if antenna:
        c.rect(x0 + 32, y0 - 6, 4, 12, DARK)
        c.rect(x0 + 29, y0 - 10, 10, 6, eye)
    if arms_up:                                                       # arms
        c.rect(x0 - 2, y0 + 8, 8, 30, METAL)
        c.rect(x0 + 62, y0 + 8, 8, 30, METAL)
    else:
        c.rect(x0 - 2, y0 + 36, 8, 26, METAL)
        c.rect(x0 + 62, y0 + 36, 8, 26, METAL)
    return c.png()


def make_robot():
    d = ROOT / "assets" / "characters" / "robot"
    d.mkdir(parents=True, exist_ok=True)
    green, red = (90, 235, 120, 255), (255, 70, 60, 255)
    frames = {
        "walk_0": robot(leg=6), "walk_1": robot(leg=0, bob=-2), "walk_2": robot(leg=-6),
        "walk_3": robot(leg=0, bob=-2),
        "idle_0": robot(), "idle_1": robot(antenna=False, bob=1),
        "reminder_0": robot(eye=(255, 220, 60, 255)), "reminder_1": robot(eye=(255, 220, 60, 255), bob=-3),
        "happy_0": robot(eye=green, arms_up=True, bob=-8), "happy_1": robot(eye=green, arms_up=True),
        "angry_0": robot(eye=red, shake=-3), "angry_1": robot(eye=red, shake=3),
    }
    for name, data in frames.items():
        (d / (name + ".png")).write_bytes(data)
    manifest = {
        "id": "robot", "name": "Robo (sample)", "size": [96, 96], "faces": "left",
        "animations": {
            "walk": {"type": "png_sequence", "pattern": "walk_*.png", "fps": 8},
            "idle": {"type": "png_sequence", "pattern": "idle_*.png", "fps": 2},
            "reminder": {"type": "png_sequence", "pattern": "reminder_*.png", "fps": 4},
            "happy": {"type": "png_sequence", "pattern": "happy_*.png", "fps": 6},
            "angry": {"type": "png_sequence", "pattern": "angry_*.png", "fps": 14},
        },
    }
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    make_sounds()
    make_robot()
    print("assets generated under", ROOT / "assets")
