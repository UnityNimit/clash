# check_window.py
import win32gui

# --- The EXACT title of the window we are looking for ---
TARGET_TITLE = "BlueStacks App Player"

print(f"Searching for a window with the exact title: '{TARGET_TITLE}'...")

# The function to find the window
hwnd = win32gui.FindWindow(None, TARGET_TITLE)

# Check the result
if hwnd != 0:
    print("\nSUCCESS! Window Found.")
    print(f"The window handle (HWND) is: {hwnd}")
else:
    print("\nFAILURE: Window NOT Found.")
    print("This means the window title is likely incorrect or the window is not open.")