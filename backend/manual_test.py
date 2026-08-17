"""
Stage 2 hardware test -- run this on the laptop while it's joined to
Cozmo's WiFi hotspot. No browser, no curl, just watch Cozmo and read the
terminal.

This exercises the same CozmoService code the Flask app (app.py) uses, just
called directly instead of over HTTP -- the HTTP layer itself was already
verified separately with a fake connection, so this is purely about
confirming the real hardware calls work.

IMPORTANT: sending a command to Cozmo (e.g. service.play_animation(...))
never raises an error just because his WiFi link dropped -- commands travel
as one-way UDP packets, so "the code didn't crash" is NOT proof Cozmo
actually got them. After every step, this script checks service.is_alive(),
which is only true if Cozmo has sent something back to us recently. That's
the real signal of whether the link is still up, not print statements.

Run it with:
    "D:\\Projects\\Cozmo Dashboard\\.venv\\Scripts\\python.exe" backend\\manual_test.py
"""

import pathlib
import time

import pycozmo

from cozmo_service import service

# Always save next to this script, regardless of what folder the launcher
# (e.g. the .bat file, or a terminal opened elsewhere) was run from.
CAMERA_TEST_PATH = pathlib.Path(__file__).parent / "camera_test.jpg"

# Track whether every step saw a live connection, for the honest summary
# at the end -- separate from whether the Python code itself ran cleanly.
_all_alive = True


def step(description: str) -> None:
    print(f"\n>>> {description}")


def check_alive() -> None:
    """Call this right after each action to confirm Cozmo is still really
    there, instead of assuming a command worked just because sending it
    didn't raise an exception."""
    global _all_alive
    if service.is_alive():
        age = service.seconds_since_last_response()
        print(f"    (Cozmo responded {age:.1f}s ago -- link looks solid.)")
    else:
        _all_alive = False
        age = service.seconds_since_last_response()
        print(f"    !! WARNING: no response from Cozmo in {age:.1f}s.")
        print("    !! WiFi link may have dropped -- this step may NOT have")
        print("    !! actually happened even though no error was raised.")


def main() -> None:
    print("Connecting to Cozmo...")
    print("(Make sure this laptop's WiFi is joined to Cozmo's hotspot first.)")
    service.connect()
    print("Connected!")

    step("Driving forward for 1 second, then stopping -- watch Cozmo roll forward.")
    service.drive(left=60, right=60)   # mm/s, well under his ~200mm/s max
    time.sleep(1.0)
    service.stop_drive()
    time.sleep(0.5)
    check_alive()

    step("Turning in place for 1 second -- watch Cozmo spin.")
    service.drive(left=-40, right=40)
    time.sleep(1.0)
    service.stop_drive()
    time.sleep(0.5)
    check_alive()

    step("Tilting head up then down -- watch his head move.")
    service.set_head_angle(angle=0.4, duration=0.8)
    time.sleep(1.0)
    service.set_head_angle(angle=-0.2, duration=0.8)
    time.sleep(1.0)
    check_alive()

    step("Raising then lowering the lift -- watch his arm/lift move.")
    service.set_lift_height(height=90, duration=0.8)
    time.sleep(1.0)
    service.set_lift_height(height=32, duration=0.8)
    time.sleep(1.0)
    check_alive()

    step("Playing the 'happy' animation -- watch his face/body react.")
    service.play_animation("happy")
    time.sleep(3.0)
    check_alive()

    step("Speaking a test phrase -- listen for audio from Cozmo's speaker.")
    service.say("Hello! I am Cozmo, and I am working.")
    # say() blocks until playback finishes when called directly like this.
    check_alive()

    step(f"Grabbing a camera snapshot -- will be saved to {CAMERA_TEST_PATH}")
    # Try a few times -- the very first frame or two after enabling the
    # camera can be dropped/incomplete over WiFi, which is normal.
    jpeg = None
    for attempt in range(5):
        jpeg = service.get_latest_jpeg(timeout=3.0)
        if jpeg:
            break
        print(f"  (attempt {attempt + 1}/5: no frame yet, retrying...)")
    if jpeg:
        CAMERA_TEST_PATH.write_bytes(jpeg)
        print(f"Saved {CAMERA_TEST_PATH} -- open it to see what Cozmo sees.")
    else:
        print("No camera frame received after several attempts -- camera may need troubleshooting.")
    check_alive()

    print()
    if _all_alive:
        print("ALL STEPS CONFIRMED: Cozmo was responding after every single step,")
        print("so everything above genuinely reached him and Stage 2 is fully working.")
    else:
        print("SOME STEPS ARE UNCONFIRMED: at least one WARNING appeared above, meaning")
        print("Cozmo's WiFi link looked dead right after that step. Compare what you saw")
        print("physically against the steps that warned -- likely causes are Cozmo")
        print("wandering out of WiFi range, or something blocking the signal. Try")
        print("running this again with Cozmo closer to the laptop.")

    service.disconnect()


if __name__ == "__main__":
    try:
        main()
    except pycozmo.exception.PyCozmoException as e:
        print(f"\nCozmo connection error: {e}")
        print("Double check this laptop's WiFi is connected to Cozmo's hotspot,")
        print("and that Cozmo is awake (not asleep/on charger with screen off).")
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
