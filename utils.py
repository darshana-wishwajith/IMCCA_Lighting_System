#!/usr/bin/env python3
"""
Utility functions for Mortal Kombat LED lighting system
"""

import time
from config import GAME_PROCESS_NAMES


class GameDetector:
    def __init__(self):
        self.last_detected = 0
        self.detected = False
        self.cache_time = 0

    def detect_game(self, game_process_names=None):
        """Detect if game is running (with 2-second cache)."""
        if game_process_names is None:
            game_process_names = GAME_PROCESS_NAMES

        try:
            import psutil

            # Refresh cache every 2 seconds
            current_time = time.time()
            if current_time - self.cache_time < 2:
                return self.detected

            self.cache_time = current_time
            self.detected = False

            for proc in psutil.process_iter(['name', 'pid']):
                try:
                    proc_name = proc.info['name'].lower() if proc.info['name'] else ""
                    for game_name in game_process_names:
                        if game_name.lower() in proc_name:
                            self.detected = True
                            self.last_detected = time.time()
                            return True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass

            # If we haven't detected the game recently, set to False
            if time.time() - self.last_detected > 5:
                self.detected = False

            return self.detected

        except Exception as e:
            print(f"Game detection error: {e}")
            return False