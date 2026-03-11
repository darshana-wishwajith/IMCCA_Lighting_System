#!/usr/bin/env python3
"""
Configuration settings for Mortal Kombat LED lighting system
"""

# Screen Resolution
SCREEN_WIDTH  = 3840
SCREEN_HEIGHT = 2160

# ── Health Bar Regions ────────────────────────────────────────────────────────
# MK11 health bars sit near the very top of the screen.
# P1 bar: yellow anchored at CENTER side, depletes outward (left).
# P2 bar: mirrored – yellow on left / inner side, depletes outward (right).

HEALTH_BAR_REGION = {
    'top':    0.06,
    'left':   0.05,
    'width':  0.41,
    'height': 0.025,
}

OPPONENT_HEALTH_BAR_REGION = {
    'top':    0.06,
    'left':   0.54,
    'width':  0.41,
    'height': 0.025,
}

# ── Health Bar Colors (HSV) ───────────────────────────────────────────────────
HEALTH_BAR_HSV_WIDER_LOWER  = (15,   80,  80)
HEALTH_BAR_HSV_WIDER_UPPER  = (45,  255, 255)

# Red damage indicator – the red section that appears between depleted space
# and the current yellow bar showing exactly how much health was just lost.
DAMAGE_INDICATOR_HSV_LOWER  = (  0, 150, 150)
DAMAGE_INDICATOR_HSV_UPPER  = (  8, 255, 255)
DAMAGE_INDICATOR_HSV_LOWER2 = (172, 150, 150)   # hue wrap-around
DAMAGE_INDICATOR_HSV_UPPER2 = (180, 255, 255)

# ── Game Detection ────────────────────────────────────────────────────────────
GAME_PROCESS_NAMES = [
    "MK11.exe",
    "MK11_DX12.exe",
    "mortal kombat.exe",
    "mkx.exe",
    "mka.exe",
]

# ── Serial / Update ───────────────────────────────────────────────────────────
SERIAL_PORT           = 'COM6'
SERIAL_BAUD           = 9600
HEALTH_CHECK_INTERVAL = 0.1

# ── LED Settings ──────────────────────────────────────────────────────────────
LED_BRIGHTNESS              = 200
ANIMATION_SPEED             = 1.0

# ── Combat Detection ──────────────────────────────────────────────────────────
COMBO_DAMAGE_THRESHOLD  = 10
COMBO_TIMEOUT           = 0.5

LIGHT_HIT_THRESHOLD    =  3
MEDIUM_HIT_THRESHOLD   =  8
HEAVY_HIT_THRESHOLD    = 13
CRITICAL_HIT_THRESHOLD = 20


# ── Screen State Detection ────────────────────────────────────────────────────

# Fully black screen → LOADING
LOADING_BRIGHTNESS_THRESHOLD = 8

# Character-select screen – both outer edge strips are vivid + bright
CHAR_SELECT_SATURATION_THRESHOLD = 60
CHAR_SELECT_BRIGHTNESS_THRESHOLD = 80

# PRE_CINEMATIC: both health bars sit at ≥95% for this long before confirming
PRE_CINEMATIC_MIN_DURATION = 1.5
PRE_CINEMATIC_TIMEOUT      = 8.0   # safety: force IN_MATCH after this long

END_MATCH_DURATION         = 10.0
STATE_CHANGE_COOLDOWN      = 0.5
MATCH_END_ABSENCE_DURATION = 2.0

# ── PRE_SEQUENCE: fight scene visible but no health-bar HUD ──────────────────
# Detected by inter-frame motion in the arena region (fighters moving around).
# Arena fight scenes have large pixel changes each frame; lobby menus do not.

# Screen region sampled for motion (avoids the HUD strip at the top)
PRE_SEQUENCE_REGION = {
    'top':    0.15,
    'left':   0.10,
    'width':  0.80,
    'height': 0.70,
}

# Downsample resolution for speed
PRE_SEQUENCE_SAMPLE_W = 320
PRE_SEQUENCE_SAMPLE_H = 180

# A pixel counts as "changed" when its grayscale diff exceeds this value
PRE_SEQUENCE_PIXEL_CHANGE_VALUE = 25

# Fraction of sampled pixels that must change per frame to confirm arena motion
PRE_SEQUENCE_MOTION_THRESHOLD = 0.06    # 6 %

# Motion must be sustained for this long before entering PRE_SEQUENCE
PRE_SEQUENCE_ENTRY_DURATION = 0.4       # seconds

# ── Audio Reactivity (PRE_SEQUENCE white/green pattern) ──────────────────────
# Python captures system audio via sounddevice WASAPI loopback and sends
# AUDIO_LEVEL:XX (0-100) to the Arduino at AUDIO_UPDATE_INTERVAL.
# If no loopback device is found, animation still runs at medium brightness.

AUDIO_SAMPLE_RATE     = 48000     # Higher sample rate is more stable on WASAPI
AUDIO_BLOCK_SIZE      = 1024      # Increased block size for 44.1kHz
AUDIO_GAIN            = 850.0     # Increased gain for much stronger color pops
AUDIO_UPDATE_INTERVAL = 0.05      # seconds between AUDIO_LEVEL commands
AUDIO_SMOOTHING       = 0.25      # Faster reaction (less lag)
AUDIO_DEVICE_INDEX    = 31        # Stereo Mix (WASAPI)

# High-frequency "sparkle" effect (on top of other modes)
HIGH_FREQ_MIN             = 4000     # Hz
HIGH_FREQ_MAX             = 11025    # Hz (max for 22050 SR)
HIGH_FREQ_GAIN            = 15.0     # Significantly increased gain for top priority
HIGH_FREQ_SMOOTHING       = 0.20     # Ultra-fast response for sharp impacts
HIGH_FREQ_UPDATE_INTERVAL = 0.03     # Smoother, higher-freq updates

# ── Lobby Input Detection ─────────────────────────────────────────────────────
# Any keyboard key-press or gamepad button while in LOBBY triggers LOBBY_INPUT
# → brown flash on the LED strip.
# The cooldown prevents held keys from spamming the Arduino.
LOBBY_INPUT_COOLDOWN = 0.18       # seconds between LOBBY_INPUT commands

# ── Dialog Detection (Pre-Cinematic character speeches) ───────────────────────
DIALOG_REGION = {
    'top':    0.80,
    'left':   0.15,
    'width':  0.70,
    'height': 0.12,
}

DIALOG_BOX_MAX_AVG_BRIGHTNESS = 55
DIALOG_TEXT_MIN_BRIGHTNESS    = 200
DIALOG_TEXT_MIN_PIXEL_COUNT   = 80
DIALOG_LINE_CHANGE_THRESHOLD  = 0.12

# ── Debug ─────────────────────────────────────────────────────────────────────
DEBUG     = False
