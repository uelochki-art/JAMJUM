"""
Generates a starter sound kit (one-shots and backing track demo)
using wave and numpy for immediate out-of-the-box testing.
"""

import os
import wave
import struct
import numpy as np

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
os.makedirs(SAMPLE_DIR, exist_ok=True)
SR = 44100


def save_wav(filename: str, samples: np.ndarray):
    path = os.path.join(SAMPLE_DIR, filename)
    samples = np.clip(samples, -1.0, 1.0)
    int_samples = (samples * 32767).astype(np.int16)

    # Make stereo
    stereo = np.column_stack((int_samples, int_samples))

    with wave.open(path, 'w') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(stereo.tobytes())
    return path


def gen_kick():
    t = np.linspace(0, 0.35, int(SR * 0.35))
    freq = 150 * np.exp(-t * 18) + 45
    phase = 2 * np.pi * np.cumsum(freq) / SR
    env = np.exp(-t * 12)
    return np.sin(phase) * env


def gen_snare():
    t = np.linspace(0, 0.25, int(SR * 0.25))
    noise = np.random.uniform(-1, 1, len(t))
    tone = np.sin(2 * np.pi * 180 * t) * np.exp(-t * 20)
    env = np.exp(-t * 15)
    return (0.7 * noise + 0.3 * tone) * env


def gen_hihat():
    t = np.linspace(0, 0.08, int(SR * 0.08))
    noise = np.random.uniform(-1, 1, len(t))
    env = np.exp(-t * 60)
    return noise * env


def gen_clap():
    dur = int(SR * 0.2)
    s = np.zeros(dur)
    for delay in [0, 0.012, 0.024, 0.036]:
        idx = int(delay * SR)
        l = min(int(0.04 * SR), dur - idx)
        s[idx:idx+l] += np.random.uniform(-0.8, 0.8, l) * np.linspace(1, 0, l)
    return s


def gen_stab(note_freq=440):
    t = np.linspace(0, 0.5, int(SR * 0.5))
    s = (np.sin(2 * np.pi * note_freq * t) +
         0.5 * np.sin(2 * np.pi * note_freq * 2 * t) +
         0.25 * np.sin(2 * np.pi * note_freq * 3 * t))
    env = np.exp(-t * 6)
    return s * env * 0.6


def gen_track_demo(bpm=120):
    """Generates an 8-bar electronic backing track demo (~16 seconds)."""
    beat_dur = 60.0 / bpm
    bar_dur = beat_dur * 4
    total_dur = bar_dur * 4  # 4 bars
    total_samples = int(SR * total_dur)
    track = np.zeros(total_samples)

    kick = gen_kick()
    snare = gen_snare()
    hihat = gen_hihat()

    # 4 beats per bar
    for bar in range(4):
        for beat in range(4):
            t_beat = (bar * 4 + beat) * beat_dur
            idx = int(t_beat * SR)

            # Kick on 0, 2
            if beat in (0, 2):
                l = min(len(kick), total_samples - idx)
                track[idx:idx+l] += kick[:l] * 0.8

            # Snare on 1, 3
            if beat in (1, 3):
                l = min(len(snare), total_samples - idx)
                track[idx:idx+l] += snare[:l] * 0.7

            # Hihat every 8th
            for eighth in [0, 0.5]:
                h_idx = int((t_beat + eighth * beat_dur) * SR)
                if h_idx < total_samples:
                    l = min(len(hihat), total_samples - h_idx)
                    track[h_idx:h_idx+l] += hihat[:l] * 0.4

    # Add a simple synth bassline
    t = np.linspace(0, total_dur, total_samples)
    bass_freq = 55  # A1
    bass = np.sin(2 * np.pi * bass_freq * t) * 0.35
    track += bass
    return track


def main():
    print("Generating demo sound kit...")
    save_wav("Kick.wav", gen_kick())
    save_wav("Snare.wav", gen_snare())
    save_wav("HiHat.wav", gen_hihat())
    save_wav("Clap.wav", gen_clap())
    save_wav("Synth_C.wav", gen_stab(261.63))
    save_wav("Synth_E.wav", gen_stab(329.63))
    save_wav("Synth_G.wav", gen_stab(392.00))
    save_wav("Synth_B.wav", gen_stab(493.88))
    save_wav("Backing_Track_120BPM.wav", gen_track_demo(120))
    print(f"Demo sound kit created successfully in: {SAMPLE_DIR}")


if __name__ == "__main__":
    main()
