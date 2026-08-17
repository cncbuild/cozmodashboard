"""
Stage 2 hardware test -- run this on the laptop while it's joined to
Cozmo's WiFi hotspot. No browser, no curl, just watch Cozmo and read the
terminal.

This exercises the same CozmoService code the Flask app (app.py) uses, just
called directly instead of over HTTP -- the HTTP layer itself was already
verified separately with a fake connection, so this is purely about
confirming the real hardware calls work.

Run it with:
    "D:\\Projects\\Cozmo Dashboard\\.venv\\Scripts\\python.exe" backend\\manual_test.py
"""

import time

import pycozmo

from cozmo_service import service


def step(description: str) -> None:
    print(f"\n>>> {description}")


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

    step("Turning in place for 1 second -- watch Cozmo spin.")
    service.drive(left=-40, right=40)
    time.sleep(1.0)
    service.stop_drive()
    time.sleep(0.5)

    step("Tilting head up then down -- watch his head move.")
    service.set_head_angle(angle=0.4, duration=0.8)
    time.sleep(1.0)
    service.set_head_angle(angle=-0.2, duration=0.8)
    time.sleep(1.0)

    step("Raising then lowering the lift -- watch his arm/lift move.")
    service.set_lift_height(height=90, duration=0.8)
    time.sleep(1.0)
    service.set_lift_height(height=32, duration=0.8)
    time.sleep(1.0)

    step("Playing the 'happy' animation -- watch his face/body react.")
    service.play_animation("happy")
    time.sleep(3.0)

    step("Speaking a test phrase -- listen for audio from Cozmo's speaker.")
    service.say("Hello! I am Cozmo, and I am working.")
    # say() blocks until playback finishes when called directly like this.

    step("Grabbing a camera snapshot -- saved to camera_test.jpg in this folder.")
    jpeg = service.get_latest_jpeg(timeout=3.0)
    if jpeg:
        with open("camera_test.jpg", "wb") as f:
            f.write(jpeg)
        print("Saved camera_test.jpg -- open it to see what Cozmo sees.")
    else:
        print("No camera frame received within 3 seconds -- camera may need troubleshooting.")

    print("\nAll checks sent. If Cozmo drove, turned, moved his head/lift,")
    print("played an animation, spoke the phrase out loud, and a")
    print("camera_test.jpg was saved, Stage 2 is fully working.")

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
