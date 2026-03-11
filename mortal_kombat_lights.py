#!/usr/bin/env python3
"""
Mortal Kombat LED Lighting System  –  Python controller for Arduino LED strip

v5.0 changes
------------
* PRE_SEQUENCE state: fight scene on screen but no health-bar HUD.
  Detected via inter-frame motion in the arena region.
  Sends AUDIO_LEVEL:XX every 50 ms so Arduino can drive the white/green
  audio-reactive pattern.
* Audio capture: system output captured via sounddevice WASAPI loopback.
  Falls back gracefully if no loopback device is available.
* Lobby input detection: pynput keyboard + optional gamepad (inputs lib).
  Any key/button press in LOBBY → LOBBY_INPUT command → brown flash.
* PRE_SEQUENCE interrupt: any game input immediately forces a state
  re-evaluation on the next loop tick, bypassing the cooldown.
"""

import sys
import time
import serial
import psutil
import mss
import cv2
import numpy as np
from PIL import Image
from threading import Thread, Event, Lock
from config import *

# ── Screen state labels ───────────────────────────────────────────────────────
STATE_NO_GAME      = 'NO_GAME'
STATE_LOADING      = 'LOADING'
STATE_LOBBY        = 'LOBBY'
STATE_CHAR_SELECT  = 'CHAR_SELECT'
STATE_PRE_CIN      = 'PRE_CINEMATIC'
STATE_PRE_SEQUENCE = 'PRE_SEQUENCE'
STATE_IN_MATCH     = 'IN_MATCH'
STATE_END_MATCH    = 'END_MATCH'

# States in which player input is monitored
INPUT_SENSITIVE_STATES = {STATE_LOBBY, STATE_PRE_SEQUENCE}


class MortalKombatLights:
    def __init__(self, screen_width=None, screen_height=None):
        self.arduino    = None
        self.running    = True
        self.stop_event = Event()

        # ── State machine ────────────────────────────────────────────────────
        self.current_screen_state = STATE_NO_GAME
        self.state_change_time    = time.time()

        self.both_health_full_since     = 0.0
        self.health_absent_since        = 0.0
        self._input_interrupt           = False   # bypass cooldown on next tick

        # ── Match tracking ───────────────────────────────────────────────────
        self.game_running    = False
        self.in_match        = False
        self.player_health   = 100
        self.previous_health = 100

        self.last_health_time = time.time()
        self.combo_active     = False
        self.combo_hits       = 0

        self.round_number     = 0
        self.round_start_time = 0.0

        self.opponent_health          = 100
        self.previous_opponent_health = 100
        self.last_opponent_hit_time   = 0.0
        self.player_combo_count       = 0

        self.finish_him_detected   = False
        self.fatality_window_start = 0.0

        # ── Dialog tracking ──────────────────────────────────────────────────
        self.dialog_box_active  = False
        self.last_dialog_region = None
        self.dialog_cooldown    = 0.0

        # ── PRE_SEQUENCE motion detection ────────────────────────────────────
        self._prev_motion_frame     = None          # last downsampled gray frame
        self._motion_detected_since = 0.0           # timestamp motion first seen
        self._last_motion_value     = 0.0           # 0.0-1.0 fraction changed

        # ── Audio capture ────────────────────────────────────────────────────
        self._audio_level       = 50                # current smoothed level 0-100
        self._audio_lock        = Lock()
        self._audio_available   = False
        self._audio_stream      = None
        self._last_audio_send   = 0.0
        self._high_freq_level   = 0.0
        self._last_high_freq_send = 0.0

        # ── Input detection ──────────────────────────────────────────────────
        self._last_lobby_input  = 0.0
        self._input_listener_kb = None
        self._input_listener_ms = None
        self._gamepad_thread    = None

        # ── Screen capture ───────────────────────────────────────────────────
        self.sct           = mss.mss()
        self.screen_width  = screen_width  or SCREEN_WIDTH
        self.screen_height = screen_height or SCREEN_HEIGHT

        self.update_health_bar_region()

        # Optional utils module (GameDetector adds 2s process-scan cache)
        try:
            from utils import GameDetector
            self.game_detector = GameDetector()
            self.use_utils     = True
        except Exception as e:
            print(f"Warning: Could not load utils module: {e}")
            self.use_utils = False

    # ─────────────────────────────────────────────────────────────────────────
    # Region setup
    # ─────────────────────────────────────────────────────────────────────────

    def update_health_bar_region(self):
        """Convert config percentage values to absolute pixel regions."""
        self.health_bar_region = {
            'top':    int(self.screen_height * HEALTH_BAR_REGION['top']),
            'left':   int(self.screen_width  * HEALTH_BAR_REGION['left']),
            'width':  int(self.screen_width  * HEALTH_BAR_REGION['width']),
            'height': int(self.screen_height * HEALTH_BAR_REGION['height']),
        }
        self.expected_health_width = self.health_bar_region['width']

        self.opponent_health_bar_region = {
            'top':    int(self.screen_height * OPPONENT_HEALTH_BAR_REGION['top']),
            'left':   int(self.screen_width  * OPPONENT_HEALTH_BAR_REGION['left']),
            'width':  int(self.screen_width  * OPPONENT_HEALTH_BAR_REGION['width']),
            'height': int(self.screen_height * OPPONENT_HEALTH_BAR_REGION['height']),
        }
        self.expected_opponent_health_width = self.opponent_health_bar_region['width']

        self.dialog_pixel_region = {
            'top':    int(self.screen_height * DIALOG_REGION['top']),
            'left':   int(self.screen_width  * DIALOG_REGION['left']),
            'width':  int(self.screen_width  * DIALOG_REGION['width']),
            'height': int(self.screen_height * DIALOG_REGION['height']),
        }

        # PRE_SEQUENCE motion sampling region (absolute pixels)
        self._motion_region = {
            'top':    int(self.screen_height * PRE_SEQUENCE_REGION['top']),
            'left':   int(self.screen_width  * PRE_SEQUENCE_REGION['left']),
            'width':  int(self.screen_width  * PRE_SEQUENCE_REGION['width']),
            'height': int(self.screen_height * PRE_SEQUENCE_REGION['height']),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Arduino
    # ─────────────────────────────────────────────────────────────────────────

    def connect_arduino(self):
        ports = [SERIAL_PORT, 'COM3', 'COM4', 'COM5', 'COM6', 'COM7',
                 '/dev/ttyUSB0', '/dev/ttyACM0']
        for port in ports:
            try:
                self.arduino = serial.Serial(port, SERIAL_BAUD, timeout=1)
                time.sleep(2)
                print(f"Connected to Arduino on {port}")
                self.send_command(f"BRIGHTNESS:{LED_BRIGHTNESS}")
                self.send_command(f"SPEED:{int(ANIMATION_SPEED * 100)}")
                return True
            except Exception:
                continue
        print("Could not connect to Arduino on any port")
        return False

    def send_command(self, command) -> bool:
        try:
            if self.arduino and self.arduino.is_open:
                self.arduino.write(f"{command}\n".encode())
                self.arduino.flush()
                time.sleep(0.01)
                return True
        except Exception as e:
            if DEBUG: print(f"Command send error: {e}")
        return False

    # ─────────────────────────────────────────────────────────────────────────
    # Audio capture
    # ─────────────────────────────────────────────────────────────────────────

    def _find_loopback_device(self):
        """Find a WASAPI loopback / Stereo Mix device index, or None."""
        try:
            import sounddevice as sd
            # If manual override is set in config, use it directly
            if getattr(self, 'audio_device_index', None) is not None:
                return self.audio_device_index
            
            # Check if AUDIO_DEVICE_INDEX is defined in config
            try:
                from config import AUDIO_DEVICE_INDEX
                if AUDIO_DEVICE_INDEX is not None:
                    return AUDIO_DEVICE_INDEX
            except ImportError:
                pass

            devices = sd.query_devices()
            
            # Priority 1: Specifically look for WASAPI loopback/stereo mix
            for i, d in enumerate(devices):
                name = d['name'].lower()
                hostapi = sd.query_hostapis(d['hostapi'])['name']
                if 'wasapi' in hostapi.lower():
                    if ('loopback' in name or 'stereo mix' in name or
                        'what u hear' in name or 'wave out mix' in name):
                        if d['max_input_channels'] > 0:
                            return i
            
            # Priority 2: Look for any stereo mix/loopback
            for i, d in enumerate(devices):
                name = d['name'].lower()
                if ('loopback' in name or 'stereo mix' in name or
                    'what u hear' in name or 'wave out mix' in name):
                    if d['max_input_channels'] > 0:
                        return i
            return None
        except Exception:
            return None

    def _audio_callback(self, indata, frames, time_info, status):
        """Called by sounddevice in its own thread for each audio block."""
        # Handle potential multi-channel input
        mono_data = indata[:, 0] if indata.shape[1] > 0 else indata
        
        # ── 1. Broad audio level (RMS) for PRE_SEQUENCE pattern ──────────────
        rms = float(np.sqrt(np.mean(mono_data ** 2)))
        raw = min(100.0, rms * AUDIO_GAIN)

        # ── 2. High-frequency detection (FFT) for sparkle overlay ────────────
        try:
            # Simple FFT on the mono block
            fft_data = np.abs(np.fft.rfft(mono_data))
            freqs    = np.fft.rfftfreq(len(mono_data), 1.0 / AUDIO_SAMPLE_RATE)

            # Sum magnitudes in the high-frequency range (4kHz - 11kHz)
            mask = (freqs >= HIGH_FREQ_MIN) & (freqs <= HIGH_FREQ_MAX)
            hf_mag = float(np.mean(fft_data[mask])) if np.any(mask) else 0.0
            hf_raw = min(255.0, hf_mag * HIGH_FREQ_GAIN)
        except Exception:
            hf_raw = 0.0

        with self._audio_lock:
            # Smooth both levels
            self._audio_level = (self._audio_level * AUDIO_SMOOTHING +
                                 raw * (1.0 - AUDIO_SMOOTHING))

            self._high_freq_level = (self._high_freq_level * HIGH_FREQ_SMOOTHING +
                                     hf_raw * (1.0 - HIGH_FREQ_SMOOTHING))

    def start_audio(self):
        """Start system-audio capture in the background. Safe to call once."""
        try:
            import sounddevice as sd
            device = self._find_loopback_device()
            if device is None:
                print("Audio: no loopback device found – trying default input.")
            else:
                print(f"Audio: using device index {device}")
            self._audio_stream = sd.InputStream(
                device=device,
                channels=2,  # Stereo Mix usually requires 2 channels
                samplerate=AUDIO_SAMPLE_RATE,
                blocksize=AUDIO_BLOCK_SIZE,
                callback=self._audio_callback,
            )
            self._audio_stream.start()
            self._audio_available = True
            name = sd.query_devices(device)['name'] if device is not None else 'default'
            print(f"Audio capture active on: {name}")
        except ImportError:
            print("Audio: sounddevice not installed – pip install sounddevice")
        except Exception as e:
            print(f"Audio capture unavailable: {e}")

    def stop_audio(self):
        if self._audio_stream:
            try:
                self._audio_stream.stop()
                self._audio_stream.close()
            except Exception:
                pass

    def get_audio_level(self) -> int:
        with self._audio_lock:
            return int(self._audio_level)

    # ─────────────────────────────────────────────────────────────────────────
    # Input detection (keyboard + gamepad)
    # ─────────────────────────────────────────────────────────────────────────

    def _register_input(self):
        """
        Called by any input listener when a key/button is pressed.
        - In LOBBY:        send LOBBY_INPUT (brown flash) with cooldown.
        - In PRE_SEQUENCE: set interrupt flag so the main loop re-evaluates
                           the state immediately on its next tick.
        """
        now   = time.time()
        state = self.current_screen_state

        if state == STATE_LOBBY:
            if now - self._last_lobby_input >= LOBBY_INPUT_COOLDOWN:
                self.send_command("LOBBY_INPUT")
                self._last_lobby_input = now
                if DEBUG: print("[Input] LOBBY_INPUT sent")

        elif state == STATE_PRE_SEQUENCE:
            # Mark interrupt; main loop will force a state re-check
            self._input_interrupt = True
            if DEBUG: print("[Input] PRE_SEQUENCE interrupted by input")

    def start_input_listeners(self):
        """Start keyboard, mouse, and optional gamepad listeners."""

        # ── Keyboard ─────────────────────────────────────────────────────────
        try:
            from pynput import keyboard as pynput_kb
            def on_press(key):
                if self.running:
                    self._register_input()
            self._input_listener_kb = pynput_kb.Listener(on_press=on_press)
            self._input_listener_kb.start()
            print("Keyboard listener active.")
        except ImportError:
            print("Keyboard: pynput not installed – pip install pynput")
        except Exception as e:
            print(f"Keyboard listener error: {e}")

        # ── Gamepad (optional) ────────────────────────────────────────────────
        try:
            import inputs as inputs_lib   # pip install inputs

            def _gamepad_loop():
                while self.running:
                    try:
                        events = inputs_lib.get_gamepad()
                        for ev in events:
                            # Button presses and significant stick movements
                            if ev.ev_type == 'Key' and ev.state == 1:
                                self._register_input()
                            elif ev.ev_type == 'Absolute' and abs(ev.state) > 15000:
                                self._register_input()
                    except Exception:
                        time.sleep(0.1)   # no gamepad connected or read error

            self._gamepad_thread = Thread(target=_gamepad_loop, daemon=True)
            self._gamepad_thread.start()
            print("Gamepad listener active.")
        except ImportError:
            print("Gamepad: inputs library not installed – pip install inputs  (optional)")
        except Exception as e:
            print(f"Gamepad listener error: {e}")

    def stop_input_listeners(self):
        if self._input_listener_kb:
            try: self._input_listener_kb.stop()
            except Exception: pass

    # ─────────────────────────────────────────────────────────────────────────
    # Low-level screen helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _grab_bgr(self, monitor: dict) -> np.ndarray:
        sct_img = self.sct.grab(monitor)
        img = Image.frombytes('RGB', sct_img.size, sct_img.rgb)
        return np.array(img)[:, :, ::-1]

    def get_center_brightness(self) -> float:
        """Average RGB brightness of the central 200×200 region."""
        try:
            cx, cy = self.screen_width // 2, self.screen_height // 2
            arr = np.array(self.sct.grab(
                {'top': cy - 100, 'left': cx - 100, 'width': 200, 'height': 200}
            ))
            return float(np.mean(arr[:, :, :3]))
        except Exception:
            return 128.0

    def detect_char_select_screen(self) -> bool:
        try:
            edge_w  = int(self.screen_width  * 0.08)
            mid_top = int(self.screen_height * 0.33)
            mid_h   = int(self.screen_height * 0.34)

            lh = cv2.cvtColor(
                self._grab_bgr({'top': mid_top, 'left': 0,
                                'width': edge_w, 'height': mid_h}),
                cv2.COLOR_BGR2HSV)
            rh = cv2.cvtColor(
                self._grab_bgr({'top': mid_top,
                                'left': self.screen_width - edge_w,
                                'width': edge_w, 'height': mid_h}),
                cv2.COLOR_BGR2HSV)

            return (np.mean(lh[:, :, 1]) > CHAR_SELECT_SATURATION_THRESHOLD and
                    np.mean(rh[:, :, 1]) > CHAR_SELECT_SATURATION_THRESHOLD and
                    np.mean(lh[:, :, 2]) > CHAR_SELECT_BRIGHTNESS_THRESHOLD and
                    np.mean(rh[:, :, 2]) > CHAR_SELECT_BRIGHTNESS_THRESHOLD)
        except Exception:
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # PRE_SEQUENCE motion detection
    # ─────────────────────────────────────────────────────────────────────────

    def _measure_arena_motion(self) -> float:
        """
        Capture the arena region, downsample, diff against the previous frame.
        Returns fraction (0.0–1.0) of pixels that changed significantly.
        Arena fight scenes → high fraction; static menus → low fraction.
        """
        try:
            bgr   = self._grab_bgr(self._motion_region)
            small = cv2.resize(bgr, (PRE_SEQUENCE_SAMPLE_W, PRE_SEQUENCE_SAMPLE_H),
                               interpolation=cv2.INTER_AREA)
            gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            if self._prev_motion_frame is None:
                self._prev_motion_frame = gray
                return 0.0

            diff    = cv2.absdiff(gray, self._prev_motion_frame)
            changed = int(np.sum(diff > PRE_SEQUENCE_PIXEL_CHANGE_VALUE))
            frac    = changed / gray.size
            self._prev_motion_frame = gray
            self._last_motion_value = frac
            return frac
        except Exception:
            return 0.0

    def _is_arena_motion_active(self, now: float) -> bool:
        """
        Returns True once arena motion has been sustained for
        PRE_SEQUENCE_ENTRY_DURATION seconds.
        """
        frac = self._measure_arena_motion()

        if frac >= PRE_SEQUENCE_MOTION_THRESHOLD:
            if self._motion_detected_since == 0.0:
                self._motion_detected_since = now
            return (now - self._motion_detected_since) >= PRE_SEQUENCE_ENTRY_DURATION
        else:
            self._motion_detected_since = 0.0
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Health bar detection
    # ─────────────────────────────────────────────────────────────────────────

    def capture_health_region(self):
        try:    return self._grab_bgr(self.health_bar_region)
        except: return None

    def capture_opponent_health_region(self):
        try:    return self._grab_bgr(self.opponent_health_bar_region)
        except: return None

    def _yellow_mask(self, hsv):
        return cv2.inRange(hsv,
            np.array(HEALTH_BAR_HSV_WIDER_LOWER),
            np.array(HEALTH_BAR_HSV_WIDER_UPPER))

    def _damage_mask(self, hsv):
        m1 = cv2.inRange(hsv,
            np.array(DAMAGE_INDICATOR_HSV_LOWER),
            np.array(DAMAGE_INDICATOR_HSV_UPPER))
        m2 = cv2.inRange(hsv,
            np.array(DAMAGE_INDICATOR_HSV_LOWER2),
            np.array(DAMAGE_INDICATOR_HSV_UPPER2))
        return cv2.bitwise_or(m1, m2)

    def detect_health_bar_presence(self, img) -> bool:
        if img is None: return False
        try:
            hsv  = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            mask = cv2.bitwise_or(self._yellow_mask(hsv), self._damage_mask(hsv))
            return cv2.countNonZero(mask) > self.health_bar_region['height'] * 10
        except Exception:
            return False

    def _measure_bar(self, img, anchored_right: bool):
        """Returns (health_pct, damage_pct, detected)."""
        if img is None:
            return 100, 0, False
        try:
            hsv         = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            total_w     = img.shape[1]
            yellow_cols = np.any(self._yellow_mask(hsv) > 0, axis=0)
            damage_cols = np.any(self._damage_mask(hsv) > 0, axis=0)

            y_count = int(np.sum(yellow_cols))
            d_count = int(np.sum(damage_cols))

            if y_count == 0:
                return 0, 0, False

            health_pct = max(0, min(100, round(y_count / total_w * 100)))
            damage_pct = max(0, min(100, round(d_count / total_w * 100)))
            return health_pct, damage_pct, True
        except Exception as e:
            if DEBUG: print(f"_measure_bar error: {e}")
            return 100, 0, False

    def detect_health(self, img):
        return self._measure_bar(img, anchored_right=True)

    def detect_opponent_health(self, img):
        return self._measure_bar(img, anchored_right=False)

    # ─────────────────────────────────────────────────────────────────────────
    # Combat helpers
    # ─────────────────────────────────────────────────────────────────────────

    def detect_attack_type(self, damage: int):
        if   damage >= CRITICAL_HIT_THRESHOLD: return "CRITICAL_HIT", damage
        elif damage >= HEAVY_HIT_THRESHOLD:    return "HEAVY_HIT",    damage
        elif damage >= MEDIUM_HIT_THRESHOLD:   return "MEDIUM_HIT",   damage
        elif damage >= LIGHT_HIT_THRESHOLD:    return "LIGHT_HIT",    damage
        else:                                  return None,            damage

    def detect_fatality_state(self, opponent_health: int) -> bool:
        t = time.time()
        if opponent_health <= 5 and self.previous_opponent_health > 5:
            self.finish_him_detected   = True
            self.fatality_window_start = t
            return True
        if self.finish_him_detected and t - self.fatality_window_start > 5:
            self.finish_him_detected = False
        return False

    def detect_combo(self, current_health: int) -> bool:
        diff = time.time() - self.last_health_time
        drop = self.previous_health - current_health
        if drop >= COMBO_DAMAGE_THRESHOLD and diff < COMBO_TIMEOUT:
            self.combo_hits  += 1
            self.combo_active = True
            return True
        if diff > COMBO_TIMEOUT:
            self.combo_hits   = 0
            self.combo_active = False
        return False

    def detect_round_transition(self, current_health: int) -> bool:
        return self.previous_health < 80 and current_health >= 95

    # ─────────────────────────────────────────────────────────────────────────
    # Game detection
    # ─────────────────────────────────────────────────────────────────────────

    def detect_game(self) -> bool:
        if self.use_utils:
            return self.game_detector.detect_game()
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                pname = proc.info['name'].lower()
                for gname in GAME_PROCESS_NAMES:
                    if gname.lower() in pname:
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return False

    # ─────────────────────────────────────────────────────────────────────────
    # Dialog detection
    # ─────────────────────────────────────────────────────────────────────────

    def _capture_dialog_region(self):
        try:
            bgr = self._grab_bgr(self.dialog_pixel_region)
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        except Exception:
            return None

    def _dialog_box_present(self, gray) -> bool:
        if gray is None: return False
        return (float(np.mean(gray)) < DIALOG_BOX_MAX_AVG_BRIGHTNESS and
                int(np.sum(gray > DIALOG_TEXT_MIN_BRIGHTNESS)) > DIALOG_TEXT_MIN_PIXEL_COUNT)

    def _dialog_line_changed(self, gray) -> bool:
        if self.last_dialog_region is None or gray is None: return False
        try:
            diff    = cv2.absdiff(gray, self.last_dialog_region)
            changed = int(np.sum(diff > 30))
            return (changed / gray.size) >= DIALOG_LINE_CHANGE_THRESHOLD
        except Exception:
            return False

    def update_dialog(self):
        now  = time.time()
        gray = self._capture_dialog_region()
        box  = self._dialog_box_present(gray)

        if box:
            if not self.dialog_box_active:
                self.send_command("DIALOG_LINE")
                print("[Dialog] New dialog line")
                self.dialog_box_active = True
                self.dialog_cooldown   = now
            elif now - self.dialog_cooldown > 0.8 and self._dialog_line_changed(gray):
                self.send_command("DIALOG_LINE")
                print("[Dialog] Dialog line changed")
                self.dialog_cooldown = now
        else:
            self.dialog_box_active = False

        self.last_dialog_region = gray

    # ─────────────────────────────────────────────────────────────────────────
    # Screen-state machine
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_current_state(self) -> str:
        now = time.time()

        # ── Input interrupt: bypass cooldown and force fresh check ────────────
        in_cooldown = (now - self.state_change_time) < STATE_CHANGE_COOLDOWN
        if self._input_interrupt:
            in_cooldown = False          # honour interrupt
            self._input_interrupt = False
            self._motion_detected_since = 0.0  # reset motion timer too

        # ── 1. Fully black screen → LOADING ──────────────────────────────────
        if self.get_center_brightness() < LOADING_BRIGHTNESS_THRESHOLD:
            self.both_health_full_since = 0.0
            self.health_absent_since    = 0.0
            self._motion_detected_since = 0.0
            return STATE_LOADING

        # ── 2. Health bars visible → PRE_CIN or IN_MATCH ─────────────────────
        img         = self.capture_health_region()
        opp_img     = self.capture_opponent_health_region()
        p_present   = self.detect_health_bar_presence(img)
        opp_present = self.detect_health_bar_presence(opp_img)

        if p_present and opp_present:
            self.health_absent_since    = 0.0
            self._motion_detected_since = 0.0

            ph, _, _ = self.detect_health(img)
            oh, _, _ = self.detect_opponent_health(opp_img)

            if ph >= 95 and oh >= 95:
                if self.both_health_full_since == 0.0:
                    self.both_health_full_since = now
                full_dur = now - self.both_health_full_since

                if full_dur > PRE_CINEMATIC_TIMEOUT:
                    return STATE_IN_MATCH
                elif full_dur > PRE_CINEMATIC_MIN_DURATION:
                    return STATE_PRE_CIN
                else:
                    return (self.current_screen_state
                            if self.current_screen_state in (STATE_PRE_CIN, STATE_IN_MATCH)
                            else STATE_IN_MATCH)
            else:
                self.both_health_full_since = 0.0
                return STATE_IN_MATCH

        # ── 3. No health bars ─────────────────────────────────────────────────
        self.both_health_full_since = 0.0

        # Coming straight out of a match/cinematic → end-match countdown
        if self.current_screen_state in (STATE_IN_MATCH, STATE_PRE_CIN):
            if self.health_absent_since == 0.0:
                self.health_absent_since = now
            if now - self.health_absent_since >= MATCH_END_ABSENCE_DURATION:
                return STATE_END_MATCH
            return self.current_screen_state

        # Sustain END_MATCH for its configured duration
        if self.current_screen_state == STATE_END_MATCH:
            if now - self.state_change_time < END_MATCH_DURATION:
                return STATE_END_MATCH

        # ── 4. Arena motion with no HUD → PRE_SEQUENCE ───────────────────────
        # Check this BEFORE char-select / lobby so fight scenes take priority.
        if not in_cooldown:
            if self._is_arena_motion_active(now):
                return STATE_PRE_SEQUENCE
            else:
                # No motion: if we were in PRE_SEQUENCE, fall through to lobby
                if self.current_screen_state == STATE_PRE_SEQUENCE:
                    self._motion_detected_since = 0.0
                    # continue to char-select / lobby detection below

        # If we're already in PRE_SEQUENCE and cooldown hasn't expired yet,
        # stay there to avoid thrashing while fighters are briefly idle.
        if self.current_screen_state == STATE_PRE_SEQUENCE and in_cooldown:
            return STATE_PRE_SEQUENCE

        # ── 5. Char-select vs Lobby ───────────────────────────────────────────
        if in_cooldown:
            return self.current_screen_state

        if self.detect_char_select_screen():
            return STATE_CHAR_SELECT

        return STATE_LOBBY

    def _handle_state_transition(self, new_state: str):
        old_state                 = self.current_screen_state
        self.current_screen_state = new_state
        self.state_change_time    = time.time()
        print(f"[State] {old_state} → {new_state}")

        DIRECT = {
            STATE_NO_GAME:      'NO_GAME',
            STATE_LOADING:      'LOADING',
            STATE_LOBBY:        'LOBBY',
            STATE_CHAR_SELECT:  'CHAR_SELECT',
            STATE_PRE_CIN:      'PRE_CINEMATIC',
            STATE_PRE_SEQUENCE: 'PRE_SEQUENCE',
            STATE_END_MATCH:    'END_MATCH',
        }
        if new_state in DIRECT:
            self.send_command(DIRECT[new_state])

        # ── Entering IN_MATCH ─────────────────────────────────────────────────
        if new_state == STATE_IN_MATCH:
            self.in_match = True
            if old_state == STATE_PRE_CIN:
                self.send_command('ROUND_START')
                print("FIGHT!")
            elif old_state not in (STATE_IN_MATCH,):
                self.round_number     = 1
                self.round_start_time = time.time()
                self.send_command('ROUND_START')

            if old_state not in (STATE_IN_MATCH,):
                self.player_health            = 100
                self.previous_health          = 100
                self.opponent_health          = 100
                self.previous_opponent_health = 100
                self.player_combo_count       = 0
                self.combo_hits               = 0
                self.finish_him_detected      = False

        # ── Leaving match / cinematic states ──────────────────────────────────
        if new_state not in (STATE_IN_MATCH, STATE_PRE_CIN, STATE_PRE_SEQUENCE):
            self.in_match               = False
            self.both_health_full_since = 0.0
            self.health_absent_since    = 0.0
            self.player_combo_count     = 0
            self.finish_him_detected    = False
            self.dialog_box_active      = False
            self.last_dialog_region     = None
            self._motion_detected_since = 0.0
            self._prev_motion_frame     = None

    # ─────────────────────────────────────────────────────────────────────────
    # Per-frame updaters
    # ─────────────────────────────────────────────────────────────────────────

    def _update_match(self):
        """Drive LEDs every frame while a match is in progress."""
        img     = self.capture_health_region()
        opp_img = self.capture_opponent_health_region()

        current_health, damage_taken, health_detected = self.detect_health(img)

        if health_detected:
            self.player_health = current_health

            if damage_taken > 0 and self.detect_combo(current_health):
                self.send_command(f"COMBO:{self.combo_hits}")
                print(f"Combo hit on you! ({self.combo_hits} hits)")

            if self.detect_round_transition(current_health):
                self.round_number    += 1
                self.round_start_time = time.time()
                self.send_command("ROUND_START")
                print(f"Round {self.round_number} started!")

            if current_health < 20 and self.previous_health >= 20:
                self.send_command("CRITICAL")
                print("Critical health!")

            self.send_command(f"HEALTH:{current_health}")
            self.previous_health  = current_health
            self.last_health_time = time.time()

        opp_health, opp_damage, opp_detected = self.detect_opponent_health(opp_img)

        if opp_detected:
            self.opponent_health = opp_health

            if opp_damage > 0:
                attack_type, dmg = self.detect_attack_type(opp_damage)
                if attack_type:
                    t = time.time()
                    if t - self.last_opponent_hit_time < COMBO_TIMEOUT:
                        self.player_combo_count += 1
                    else:
                        self.player_combo_count = 1
                    self.last_opponent_hit_time = t

                    if self.player_combo_count >= 3:
                        self.send_command(f"PLAYER_COMBO:{self.player_combo_count}")
                        print(f"Your combo! {self.player_combo_count} hits! ({attack_type}: {dmg}%)")
                    else:
                        self.send_command(attack_type)
                        print(f"{attack_type}: {dmg}% damage dealt")

                    if self.detect_fatality_state(opp_health):
                        self.send_command("FATALITY_READY")
                        print("FINISH THEM!")

            self.previous_opponent_health = opp_health
            if opp_health > 10 and self.finish_him_detected:
                self.finish_him_detected = False

    def _update_pre_cinematic(self):
        """Dialog detection during PRE_CINEMATIC."""
        self.update_dialog()

    def _update_pre_sequence(self):
        """
        Stream audio level to Arduino during PRE_SEQUENCE.
        The Arduino uses AUDIO_LEVEL:XX (0-100) to modulate its white/green
        audio-reactive pattern brightness.
        """
        now = time.time()
        if now - self._last_audio_send >= AUDIO_UPDATE_INTERVAL:
            level = self.get_audio_level() if self._audio_available else 50
            self.send_command(f"AUDIO_LEVEL:{level}")
            self._last_audio_send = now

    def _update_high_freq(self):
        """Send high-frequency sparkle intensity to Arduino."""
        now = time.time()
        if now - self._last_high_freq_send >= HIGH_FREQ_UPDATE_INTERVAL:
            with self._audio_lock:
                level = int(self._high_freq_level)
            # Only send if non-zero or just became zero (to stop sparkle)
            if level > 0 or self._high_freq_level > 0:
                self.send_command(f"HIGH_FREQ:{level}")
            self._last_high_freq_send = now

    # ─────────────────────────────────────────────────────────────────────────
    # Main loop
    # ─────────────────────────────────────────────────────────────────────────

    def update_leds(self):
        while self.running and not self.stop_event.is_set():
            try:
                if not self.detect_game():
                    if self.current_screen_state != STATE_NO_GAME:
                        self._handle_state_transition(STATE_NO_GAME)
                    time.sleep(HEALTH_CHECK_INTERVAL)
                    continue

                new_state = self._detect_current_state()
                if new_state != self.current_screen_state:
                    self._handle_state_transition(new_state)

                # Per-frame work
                if self.current_screen_state == STATE_IN_MATCH:
                    self._update_match()
                elif self.current_screen_state == STATE_PRE_CIN:
                    self._update_pre_cinematic()
                elif self.current_screen_state == STATE_PRE_SEQUENCE:
                    self._update_pre_sequence()

                # Always update high-frequency overlay if audio is active
                if self._audio_available:
                    self._update_high_freq()

                time.sleep(HEALTH_CHECK_INTERVAL)

            except Exception as e:
                print(f"Update error: {e}")
                time.sleep(1)

    # ─────────────────────────────────────────────────────────────────────────
    # Entry point
    # ─────────────────────────────────────────────────────────────────────────

    def start(self):
        print("=" * 60)
        print("Mortal Kombat LED Lighting System  v5.0")
        print("=" * 60)
        print(f"Resolution       : {self.screen_width}x{self.screen_height}")
        print(f"P1 health region : {self.health_bar_region}")
        print(f"P2 health region : {self.opponent_health_bar_region}")
        print(f"Dialog region    : {self.dialog_pixel_region}")
        print(f"LED brightness   : {LED_BRIGHTNESS}")
        print()
        print("State flow:")
        print("  NO_GAME → LOADING → LOBBY → CHAR_SELECT")
        print("          → PRE_SEQUENCE (audio-reactive, input-interruptible)")
        print("          → PRE_CINEMATIC (dialog reactions)")
        print("          → IN_MATCH → END_MATCH → LOBBY")
        print("=" * 60)

        if not self.connect_arduino():
            print("Warning: Arduino not connected – simulation mode.")

        self.start_audio()
        self.start_input_listeners()

        update_thread = Thread(target=self.update_leds, daemon=True)
        update_thread.start()

        print("System running.  Press Ctrl+C to stop.\n")
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down…")
            self.running = False
            self.stop_event.set()
            self.stop_input_listeners()
            self.stop_audio()
            update_thread.join(timeout=2)
            if self.arduino:
                self.send_command("NO_GAME")
                self.arduino.close()
            print("System stopped.")


# ─────────────────────────────────────────────────────────────────────────────

def main():
    screen_width  = SCREEN_WIDTH
    screen_height = SCREEN_HEIGHT

    if len(sys.argv) >= 3:
        screen_width  = int(sys.argv[1])
        screen_height = int(sys.argv[2])
    else:
        try:
            from screeninfo import get_monitors
            m = get_monitors()[0]
            screen_width, screen_height = m.width, m.height
            print(f"Auto-detected resolution: {screen_width}x{screen_height}")
        except Exception as e:
            print(f"Could not auto-detect resolution: {e}")
            print(f"Using default: {screen_width}x{screen_height}")

    MortalKombatLights(screen_width, screen_height).start()


if __name__ == "__main__":
    main()
