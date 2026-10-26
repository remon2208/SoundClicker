@echo off
rem Builds dist\SoundClicker.exe on Windows (needs Python 3.9+).
python -m pip install -r requirements.txt pyinstaller || exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --windowed --name SoundClicker ^
  --icon assets\app.ico --add-data "assets\app.ico;." --collect-data soundcard ^
  --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 ^
  --exclude-module scipy --exclude-module matplotlib SoundClicker.pyw || exit /b 1
echo.
echo Done: dist\SoundClicker.exe
