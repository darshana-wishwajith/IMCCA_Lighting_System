# IMCCA Lighting System — Mortal Kombat LED Controller

A real-time LED lighting system for Mortal Kombat 11 that reacts to in-game events using screen capture analysis. No webcam required.

## Features

- **Automatic game detection** — detects when MK11 is running via process monitoring
- **Health bar tracking** — real-time HSV color analysis of on-screen health bars
- **Multi-state LED patterns** — different animations for each game state
- **Audio-reactive effects** — system audio captured via WASAPI loopback drives LED brightness
- **Input detection** — keyboard and gamepad input triggers lobby animations
- **Dialog detection** — detects pre-fight character dialog for cinematic lighting

## LED Patterns

| State                              | Pattern                               |
| ---------------------------------- | ------------------------------------- |
| No game running                    | Rainbow neon flow                     |
| Game loading                       | Pulsing dark-to-bright                |
| Lobby                              | Warm amber glow, brown flash on input |
| Character select                   | Shifting purple/gold                  |
| Pre-cinematic                      | Dialog-reactive blue pulse            |
| Pre-sequence (fight scene, no HUD) | Audio-reactive white/green            |
| In match                           | Health-based gradient (green → red)   |
| End match                          | Victory/defeat animation              |

## Requirements

### Hardware

- Arduino Uno + USB cable
- WS2812B LED strip (120 LEDs) connected to pin 6
- 5 V power supply (adequate for 120 LEDs)
- Computer running Mortal Kombat 11

### Software

- Python 3.6+
- Arduino IDE with FastLED library
- Python dependencies: `pip install -r requirements.txt`

## Quick Start

1. **Upload Arduino code** — open `arduino_mortal_kombat/arduino_mortal_kombat.ino` in Arduino IDE and upload
2. **Wire the LED strip** — DIN → pin 6, 5 V → power, GND → common ground
3. **Install Python deps** — run `install.bat` (Windows) or `install.sh` (Linux/Mac)
4. **Configure** — edit `config.py` for your screen resolution and COM port
5. **Run** — `run.bat` (Windows) or `run.sh` (Linux/Mac)

## Configuration

Edit `config.py` to match your setup:

```python
SCREEN_WIDTH  = 3840          # your screen resolution
SCREEN_HEIGHT = 2160
SERIAL_PORT   = 'COM6'        # Arduino COM port
AUDIO_DEVICE_INDEX = 31       # WASAPI loopback device index
```

## File Structure

```
├── arduino_mortal_kombat/
│   └── arduino_mortal_kombat.ino   # Arduino FastLED controller
├── mortal_kombat_lights.py         # Main Python controller
├── config.py                       # Configuration settings
├── utils.py                        # Game detection utility
├── requirements.txt                # Python dependencies
├── install.bat / install.sh        # Dependency install scripts
└── run.bat / run.sh                # Launch scripts
```

## How It Works

1. Python detects when Mortal Kombat starts (process monitoring)
2. Screen regions are captured via MSS and analyzed with OpenCV
3. Health bars are detected using HSV color masking (yellow = health, red = damage)
4. Game state is determined by a state machine (loading → lobby → char select → match)
5. Commands are sent to Arduino over serial (e.g., `HEALTH:75`, `COMBO:3`, `LOBBY_INPUT`)
6. Arduino drives WS2812B animations via FastLED based on received commands

## State Flow

```
NO_GAME → LOADING → LOBBY → CHAR_SELECT
        → PRE_SEQUENCE (audio-reactive, input-interruptible)
        → PRE_CINEMATIC (dialog reactions)
        → IN_MATCH → END_MATCH → LOBBY
```

## Troubleshooting

| Problem             | Solution                                                                 |
| ------------------- | ------------------------------------------------------------------------ |
| LEDs not lighting   | Check power supply, verify DIN on pin 6, confirm Arduino upload          |
| Arduino not found   | Check COM port in `config.py`, try COM3–COM7                             |
| Health not detected | Verify screen resolution in config, adjust health bar region percentages |
| No audio reactivity | Run `pip install sounddevice`, check `AUDIO_DEVICE_INDEX` in config      |
| No game detection   | Verify game executable name matches `GAME_PROCESS_NAMES` in config       |
