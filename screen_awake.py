from wakepy import keep
import time

def keep_screen_awake():
    """Keep the screen on without mouse movement"""
    print("Keeping screen awake... Press Ctrl+C to stop")
    
    try:
        with keep.presenting():
            while True:
                # Your application logic here
                time.sleep(10)  # Just keep running
    except KeyboardInterrupt:
        print("\nStopped keeping screen awake")

if __name__ == "__main__":
    keep_screen_awake()
    