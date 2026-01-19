#!/usr/bin/env python3
"""
QLab Media Player - MPV with Persistent Window & Hardware Acceleration
ONE window, smooth content switching, hardware-accelerated video

OSC Commands:
  /video #/cue/selected/duration# #/cue/selected/infiniteLoop# file.mp4
  /image #/cue/selected/duration# file.jpg
  /stop
  /clear
"""

import os
import subprocess
import threading
import time
import json
from pathlib import Path
from pythonosc import dispatcher, osc_server, udp_client

# CRITICAL: Set DISPLAY variable
if 'DISPLAY' not in os.environ:
    os.environ['DISPLAY'] = ':0'

OSC_PORT = 53000
MPV_SOCKET = '/tmp/mpv-socket'
MEDIA_DIR = Path.home() / "media"

# Track current playback
mpv_process = None
duration_timer = None
qlab_client = None  # For sending completion messages back to QLab

def send_mpv_command(command):
    """Send command to MPV via IPC socket"""
    try:
        import socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(MPV_SOCKET)
        sock.send((json.dumps(command) + '\n').encode())
        sock.close()
        return True
    except:
        return False

def start_mpv():
    """Start persistent MPV window with hardware acceleration"""
    global mpv_process
    
    if mpv_process and mpv_process.poll() is None:
        return  # Already running
    
    # Remove old socket
    try:
        os.remove(MPV_SOCKET)
    except:
        pass
    
    print("Starting persistent MPV window...")
    
    # Create black image if needed
    black_img = Path('/tmp/black.jpg')
    if not black_img.exists():
        result = os.system('convert -size 1920x1080 xc:black /tmp/black.jpg 2>/dev/null')
        if result != 0:
            os.system('ffmpeg -f lavfi -i color=black:s=1920x1080:r=1 -frames:v 1 /tmp/black.jpg 2>/dev/null')
    
    # Start MPV with:
    # - IPC socket for control
    # - Hardware acceleration
    # - Fullscreen
    # - Starting with black image
    mpv_process = subprocess.Popen(
        [
            'mpv',
            '--fullscreen',
            '--keep-open=yes',              # Keep window open
            '--image-display-duration=inf',  # Images stay forever
            '--loop-file=inf',               # Loop current file
            '--input-ipc-server=' + MPV_SOCKET,  # Control socket
            '--no-osc',                      # No on-screen controller
            '--no-osd-bar',                  # No progress bar
            '--osd-level=0',                 # No OSD
            '--cursor-autohide=always',      # Hide cursor
            '--hwdec=auto',                  # Hardware decoding (auto-detect)
            '--vo=gpu',                      # GPU video output
            '--gpu-context=x11egl',          # Use EGL for hardware accel
            '--hwdec-codecs=all',            # Hardware decode all codecs
            str(black_img) if black_img.exists() else '--idle=yes'
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    # Wait for MPV to be ready
    print("Waiting for MPV to initialize...")
    for _ in range(20):
        if os.path.exists(MPV_SOCKET):
            time.sleep(0.5)
            print("MPV ready with hardware acceleration!")
            return
        time.sleep(0.5)
    
    print("MPV started (socket may not be ready yet)")

def load_media(filepath, loop=False):
    """Load media into persistent MPV window"""
    # Use loadfile command to switch content in same window
    cmd = {
        "command": ["loadfile", filepath, "replace"]
    }
    
    success = send_mpv_command(cmd)
    
    if success:
        # Immediately unpause to start playback instantly
        play_cmd = {
            "command": ["set_property", "pause", False]
        }
        send_mpv_command(play_cmd)
        
        # Set loop mode (do this after starting playback)
        time.sleep(0.05)
        loop_cmd = {
            "command": ["set_property", "loop-file", "inf" if loop else "no"]
        }
        send_mpv_command(loop_cmd)
    
    return success

def show_black():
    """Show black image in MPV window"""
    global duration_timer
    
    if duration_timer:
        duration_timer.cancel()
        duration_timer = None
    
    black_img = Path('/tmp/black.jpg')
    if black_img.exists():
        load_media(str(black_img), loop=True)
        print("Black screen")

def play_video(filepath, duration=0, loop=False):
    """Play video in persistent MPV window"""
    global duration_timer
    
    path = Path(filepath)
    if not path.is_absolute():
        path = MEDIA_DIR / filepath
    
    if not path.exists():
        print(f"Video not found: {path}")
        return
    
    if duration_timer:
        duration_timer.cancel()
        duration_timer = None
    
    if loop:
        print(f"Playing video: {path} (LOOPING)")
    elif duration > 0:
        print(f"Playing video: {path} (duration: {duration}s)")
    else:
        print(f"Playing video: {path} (play to completion)")
    
    # Load video into MPV (this also starts playback)
    load_media(str(path), loop=loop)
    
    # Set up duration timer if needed
    if duration > 0 and not loop:
        def switch_after_duration():
            show_black()
            print(f"Video duration complete ({duration}s) - black screen")
        
        duration_timer = threading.Timer(duration, switch_after_duration)
        duration_timer.start()

def show_image(filepath, duration=0):
    """Show image in persistent MPV window"""
    global duration_timer
    
    path = Path(filepath)
    if not path.is_absolute():
        path = MEDIA_DIR / filepath
    
    if not path.exists():
        print(f"Image not found: {path}")
        return
    
    if duration_timer:
        duration_timer.cancel()
        duration_timer = None
    
    if duration > 0:
        print(f"Displaying image: {path} (duration: {duration}s)")
    else:
        print(f"Displaying image: {path} (indefinitely)")
    
    # Load image into MPV (always loop images)
    load_media(str(path), loop=True)
    
    # Set up duration timer if needed
    if duration > 0:
        def switch_after_duration():
            show_black()
            print(f"Image duration complete ({duration}s) - black screen")
        
        duration_timer = threading.Timer(duration, switch_after_duration)
        duration_timer.start()

def stop_playback():
    """Stop playback"""
    cmd = {"command": ["stop"]}
    send_mpv_command(cmd)
    print("Stopped")

def clear_to_black():
    """Clear to black screen"""
    show_black()

# OSC handlers
def osc_video(addr, *args):
    """Handle video command"""
    if len(args) == 0:
        print("ERROR: No arguments provided")
        return
    
    if len(args) == 1:
        filepath = str(args[0])
        duration = 0
        loop = False
    elif len(args) == 2:
        duration = float(args[0]) if isinstance(args[0], (int, float)) else 0
        filepath = str(args[1])
        loop = False
    else:
        duration = float(args[0]) if isinstance(args[0], (int, float)) else 0
        loop = bool(args[1]) if isinstance(args[1], (int, float)) else False
        filepath = str(args[2])
    
    print(f"\nOSC: VIDEO {filepath}" + 
          (f" duration={duration}s" if duration > 0 else "") +
          (" LOOP" if loop else ""))
    
    play_video(filepath, duration, loop)

def osc_image(addr, *args):
    """Handle image command"""
    if len(args) == 0:
        print("ERROR: No arguments provided")
        return
    
    if len(args) == 1:
        filepath = str(args[0])
        duration = 0
    else:
        duration = float(args[0]) if isinstance(args[0], (int, float)) else 0
        filepath = str(args[1])
    
    print(f"\nOSC: IMAGE {filepath}" + 
          (f" duration={duration}s" if duration > 0 else ""))
    
    show_image(filepath, duration)

def osc_stop(addr):
    print("\nOSC: STOP")
    stop_playback()

def osc_clear(addr):
    print("\nOSC: CLEAR")
    clear_to_black()

def cleanup():
    """Clean up on exit"""
    global mpv_process, duration_timer
    
    if duration_timer:
        duration_timer.cancel()
    
    if mpv_process:
        try:
            mpv_process.terminate()
            mpv_process.wait(timeout=2)
        except:
            mpv_process.kill()
    
    try:
        os.remove(MPV_SOCKET)
    except:
        pass

def main():
    print("=" * 70)
    print("QLab Media Player - MPV Persistent Window")
    print("=" * 70)
    print(f"DISPLAY: {os.environ.get('DISPLAY')}")
    print(f"Media directory: {MEDIA_DIR}")
    print("=" * 70)
    print()
    
    MEDIA_DIR.mkdir(exist_ok=True)
    
    # Start persistent MPV
    start_mpv()
    
    # Setup OSC
    disp = dispatcher.Dispatcher()
    disp.map("/video", osc_video)
    disp.map("/image", osc_image)
    disp.map("/stop", osc_stop)
    disp.map("/clear", osc_clear)
    
    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", OSC_PORT), disp)
    
    print(f"OSC Server listening on port {OSC_PORT}")
    print("\nONE persistent MPV window - smooth content switching!")
    print("Hardware acceleration enabled for smooth video")
    print("\nOSC Commands:")
    print("  /video #/cue/selected/duration# #/cue/selected/infiniteLoop# file.mp4")
    print("  /image #/cue/selected/duration# file.jpg")
    print("  /stop")
    print("  /clear")
    print("\nReady!\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        cleanup()

if __name__ == "__main__":
    main()
