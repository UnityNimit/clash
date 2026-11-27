@echo off
echo Building ClashTrainer.exe...
pyinstaller --noconsole --onefile --icon=icon.ico --collect-data customtkinter --add-data "templates;templates" --add-data "assets;assets" --add-data "icon.ico;." --name="ClashTrainer" main.py
if %ERRORLEVEL% EQU 0 (
    copy /Y "dist\ClashTrainer.exe" "ClashTrainer.exe"
    echo Build successful! ClashTrainer.exe is ready.
) else (
    echo Build failed with error code %ERRORLEVEL%.
)
pause
