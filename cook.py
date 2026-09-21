#!/usr/bin/env python3
import os
import sys
import time
import json
import shutil
import zipfile
import urllib.request
import urllib.error
import re
import threading
from datetime import datetime, timezone

REPO_OWNER = "heydevelopergit"
REPO_NAME = "Cook"
BRANCH = "main"
POTABLES_PATH = "potables"
BASE_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/raw/refs/heads/{BRANCH}/{POTABLES_PATH}"
API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{POTABLES_PATH}?ref={BRANCH}"

DB_DIR = "/var/lib/cook"
DB_FILE = os.path.join(DB_DIR, "installed.json")

BRAILLE_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']


def require_root():
    if os.geteuid() != 0:
        print("Error: root privileges required.")
        sys.exit(1)


def spinner(stop_event, message="[FETCH]"):
    idx = 0
    while not stop_event.is_set():
        frame = BRAILLE_FRAMES[idx % len(BRAILLE_FRAMES)]
        sys.stdout.write(f"\r{message} {frame}")
        sys.stdout.flush()
        idx += 1
        time.sleep(0.1)
    sys.stdout.write("\r" + " " * (len(message) + 2) + "\r")
    sys.stdout.flush()


def load_db():
    if not os.path.isfile(DB_FILE):
        return {}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_db(db):
    os.makedirs(DB_DIR, exist_ok=True)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)


def fetch_remote_packages():
    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "cook"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Error fetching package index: {e}")
        sys.exit(1)

    names = []
    for item in data:
        if item.get("type") == "file" and item["name"].endswith(".zip"):
            names.append(item["name"][:-4])
    return sorted(names)


def package_exists(package):
    zip_url = f"{BASE_URL}/{package}.zip"
    try:
        req = urllib.request.Request(zip_url, method="HEAD", headers={"User-Agent": "cook"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


def cmd_install(package):
    zip_url = f"{BASE_URL}/{package}.zip"
    zip_name = f"{package}.zip"

    if not package_exists(package):
        print(f"Package '{package}' not found in repository.")
        sys.exit(1)

    print(f"[FETCH] {zip_url}")
    stop_event = threading.Event()
    spinner_thread = threading.Thread(target=spinner, args=(stop_event,))
    spinner_thread.start()

    try:
        urllib.request.urlretrieve(zip_url, zip_name)
    except Exception as e:
        stop_event.set()
        spinner_thread.join()
        print(f"Download error: {e}")
        sys.exit(1)

    tmp_dir = f"/tmp/{os.getpid()}"
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_name, "r") as zf:
            zf.extractall(tmp_dir)
    except Exception as e:
        stop_event.set()
        spinner_thread.join()
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if os.path.exists(zip_name):
            os.remove(zip_name)
        print(f"Extraction error: {e}")
        sys.exit(1)

    list_path = os.path.join(tmp_dir, "list")
    if not os.path.isfile(list_path):
        stop_event.set()
        spinner_thread.join()
        shutil.rmtree(tmp_dir, ignore_errors=True)
        os.remove(zip_name)
        print("Error: 'list' file missing in archive.")
        sys.exit(1)

    with open(list_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    match = re.search(r"name=(.+)", content)
    if not match:
        stop_event.set()
        spinner_thread.join()
        shutil.rmtree(tmp_dir, ignore_errors=True)
        os.remove(zip_name)
        print("Error: 'name=' not found in 'list' file.")
        sys.exit(1)

    install_name = match.group(1).strip()

    stop_event.set()
    spinner_thread.join()

    main_src = os.path.join(tmp_dir, "main")
    if not os.path.isfile(main_src):
        shutil.rmtree(tmp_dir, ignore_errors=True)
        os.remove(zip_name)
        print("Error: 'main' executable missing in archive.")
        sys.exit(1)

    dest = f"/usr/bin/{install_name}"
    print(f"Installing {install_name}...")
    shutil.copy2(main_src, dest)
    os.chmod(dest, 0o755)

    db = load_db()
    db[package] = {
        "name": install_name,
        "path": dest,
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    save_db(db)

    os.remove(zip_name)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"Package '{package}' installed as '{install_name}' -> {dest}")


def cmd_remove(package):
    db = load_db()
    if package not in db:
        print(f"Package '{package}' is not installed.")
        sys.exit(1)

    entry = db[package]
    path = entry.get("path")
    if path and os.path.isfile(path):
        try:
            os.remove(path)
            print(f"Removed {path}")
        except Exception as e:
            print(f"Error removing {path}: {e}")
    else:
        print(f"Warning: {path} not found, cleaning db only.")

    del db[package]
    save_db(db)
    print(f"Package '{package}' removed.")


def cmd_search(query):
    packages = fetch_remote_packages()
    matches = [p for p in packages if query.lower() in p.lower()]
    if not matches:
        print(f"No packages matching '{query}'.")
        return
    db = load_db()
    print("Matches:")
    for p in matches:
        status = " [installed]" if p in db else ""
        print(f"  {p}{status}")


def cmd_list():
    db = load_db()
    if not db:
        print("No packages installed via cook.")
        return
    print(f"{'PACKAGE':<20} {'BINARY':<20} {'INSTALLED AT'}")
    for pkg, info in sorted(db.items()):
        print(f"{pkg:<20} {info.get('name','?'):<20} {info.get('installed_at','?')}")


def print_usage():
    print("cook - package manager for code")
    print()
    print("Usage:")
    print("  cook <package>          Cook Potable")
    print("  cook remove <package>   Remove Potable")
    print("  cook search <query>     Search Potables")
    print("  cook list               List potables")
    print()
    print(f"Repository: https://github.com/{REPO_OWNER}/{REPO_NAME}")


def main():
    require_root()

    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd in ("-h", "--help", "help"):
        print_usage()
        return

    if cmd == "list":
        cmd_list()
        return

    if cmd in ("search", "remove"):
        if len(sys.argv) != 3:
            print_usage()
            sys.exit(1)
        if cmd == "search":
            cmd_search(sys.argv[2])
        elif cmd == "remove":
            cmd_remove(sys.argv[2])
        return

    if len(sys.argv) == 2:
        cmd_install(cmd)
    else:
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()

# 1.0
