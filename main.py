# --- main.py ---

import os
import sys
import ctypes
from gui import App
from bot_core import KeyBot


def main():
    # Ensure consistent physical pixel coordinates across high-DPI displays
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    # If running from a compiled PyInstaller executable, ensure working dir is next to exe
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))

    # Create the 'templates' directory if it doesn't exist
    if not os.path.exists("templates"):
        os.makedirs("templates")
        print("Created 'templates' directory. Please add your image templates there.")

    # Set the AppUserModelID for the taskbar icon
    try:
        myappid = 'nimit.clashofclans.trainer.2.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    # Instantiate the bot and the GUI
    bot = KeyBot(
        status_callback=lambda msg: app.update_status(msg),
        resource_callback=lambda res, skipped=None: app.update_resources(res, skipped),
        log_callback=lambda line: app.append_log(line),
    )
    app = App(bot=bot)

    # Run the application
    app.mainloop()


if __name__ == "__main__":
    main()
