import time
from datetime import datetime
import ctypes

def get_screen_status():
    # This checks if the workstation is locked or the screen is effectively 'off' 
    # for the current user session.
    user32 = ctypes.windll.user32
    # Check if the desktop is locked or inaccessible (screen off/sleep)
    is_locked = user32.OpenDesktopW("Default", 0, False, 0x0100)
    if is_locked:
        user32.CloseDesktop(is_locked)
        return "ON"
    else:
        return "OFF (or Locked)"

print("--- SCREEN MONITOR START ---")
print("I will log every 5 seconds. Try turning off your screen or closing the lid.")

while True:
    now = datetime.now().strftime('%H:%M:%S')
    status = get_screen_status()
    
    output = f"[{now}] Screen is {status} | CPU is Active"
    print(output)
    
    # Writing to a file is the ONLY way to know what happened while you were away
    with open("screen_log.txt", "a") as f:
        f.write(output + "\n")
        
    time.sleep(5)