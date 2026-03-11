@echo off
echo Installing Mortal Kombat LED Lighting System...
echo.
echo Installing Python dependencies...
pip install -r requirements.txt

echo.
echo Installation complete!
echo.
echo Next steps:
echo 1. Upload arduino_mortal_kombat.ino to your Arduino
echo 2. Connect LED strip to pin 6
echo 3. Run mortal_kombat_lights.py
echo.
echo Make sure to edit config.py for your screen resolution.
pause