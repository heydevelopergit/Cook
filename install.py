#!/usr/bin/env python3
import os
import sys
import time
import urllib.request
import threading

# Cook Potables Installaton Script

FETCH_URL = "https://raw.githubusercontent.com/heydevelopergit/Cook/main/cook.py"
DEST = "/usr/bin/cook"

BRAILLE = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']


def spinner(stop_event, message):
    idx = 0
    while not stop_event.is_set():
        sys.stdout.write(f"\r{message} {BRAILLE[idx % len(BRAILLE)]}")
        sys.stdout.flush()
        idx += 1
        time.sleep(0.1)
    sys.stdout.write("\r" + " " * (len(message) + 2) + "\r")
    sys.stdout.flush()


def main():
    if os.geteuid() != 0:
        print("! No Root !")
        sys.exit(1)


    print("Cook Potables!")

    time.sleep(3)

    message = f"[FETCH] {FETCH_URL}"

    stop = threading.Event()
    t = threading.Thread(target=spinner, args=(stop, message))
    t.start()

    try:
        urllib.request.urlretrieve(FETCH_URL, DEST)
        os.chmod(DEST, 0o755)
    except Exception as e:
        stop.set()
        t.join()
        print(f"Error: {e}")
        sys.exit(1)

    stop.set()
    t.join()


if __name__ == "__main__":
    main()

# 4.0
