import os
import shutil
import json

src_root = r'c:\Users\lazyf\Music\Gussy_DAW'
dest = os.path.join(src_root, 'JAMJUM')
os.makedirs(dest, exist_ok=True)

# Copy executable
exe_src = os.path.join(src_root, 'dist', 'JAMJUM_Pad_Launcher.exe')
shutil.copy2(exe_src, os.path.join(dest, 'JAMJUM_Pad_Launcher.exe'))

# Copy icon
shutil.copy2(os.path.join(src_root, 'app_icon.ico'), os.path.join(dest, 'app_icon.ico'))

# Copy samples
samples_dest = os.path.join(dest, 'samples')
if os.path.exists(samples_dest):
    shutil.rmtree(samples_dest)
shutil.copytree(os.path.join(src_root, 'samples'), samples_dest)

# Create config.json
cfg = {
    'master_volume': 1.0,
    'volume_step': 0.05,
    'oneshot_files': {
        '0': os.path.join(samples_dest, 'Kick.wav'),
        '1': os.path.join(samples_dest, 'Snare.wav'),
        '2': os.path.join(samples_dest, 'HiHat.wav'),
        '3': os.path.join(samples_dest, 'Clap.wav'),
        '4': os.path.join(samples_dest, 'Synth_C.wav'),
        '5': os.path.join(samples_dest, 'Synth_E.wav'),
        '6': os.path.join(samples_dest, 'Synth_G.wav'),
        '7': os.path.join(samples_dest, 'Synth_B.wav')
    },
    'track_files': {
        '0': os.path.join(samples_dest, 'Backing_Track_120BPM.wav')
    },
    'preset1_midi_map': {},
    'preset2_midi_map': {}
}
with open(os.path.join(dest, 'config.json'), 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)

print('Organized successfully! Contents of JAMJUM:')
for item in os.listdir(dest):
    p = os.path.join(dest, item)
    sz = os.path.getsize(p) if os.path.isfile(p) else '<DIR>'
    print(f"  {item} ({sz})")
