"""
Cozmo connection test.

What this script does:
  1. Connects to Cozmo over WiFi (this computer must already be joined to
     Cozmo's own WiFi hotspot -- the one his charger/battery status screen
     shows when he's on, usually named something like "Cozmo_XXXXX").
  2. Waits until Cozmo has sent us his first status update (proof the
     connection is really alive, not just "socket open").
  3. Wiggles his head and lift and plays a short built-in animation, so you
     get a physical, visible confirmation -- not just text in a terminal.

Run it with:
    "D:\\Projects\\Cozmo Dashboard\\.venv\\Scripts\\python.exe" connection_test.py

If everything works, Cozmo's head/lift will move and he'll play a little
animation. If something's wrong, you'll get a clear error printed below
instead of a silent hang.
"""

import sys
import time

import pycozmo


def main() -> None:
    print("Connecting to Cozmo...")
    print("(Make sure this laptop's WiFi is joined to Cozmo's hotspot first.)")

    # pycozmo.connect() is a context manager that, in one call:
    #   - opens a UDP connection to Cozmo at his fixed WiFi address,
    #   - performs the handshake pycozmo needs to "activate" him,
    #   - blocks until the first robot status packet arrives (wait_for_robot),
    #   - and automatically disconnects cleanly when the `with` block exits,
    #     even if an error or Ctrl+C happens.
    # If Cozmo can't be reached, this will raise/exit with a clear error
    # instead of hanging forever.
    with pycozmo.connect() as cli:
        print("Connected! Cozmo is alive and responding.\n")

        # --- Move the head as a simple, fast physical proof of connection ---
        # Head angle is in radians. pycozmo.MIN_HEAD_ANGLE / MAX_HEAD_ANGLE
        # define Cozmo's real hardware limits -- stay well inside them.
        print("Moving head up...")
        cli.set_head_angle(angle=0.4, duration=1.0)  # ~23 degrees, over 1 second
        time.sleep(1.2)

        print("Moving head back down...")
        cli.set_head_angle(angle=-0.2, duration=1.0)
        time.sleep(1.2)

        # --- Move the lift too, for good measure ---
        # Lift height is in millimeters, between pycozmo.MIN_LIFT_HEIGHT (32mm,
        # fully down) and pycozmo.MAX_LIFT_HEIGHT (92mm, fully up).
        print("Raising lift...")
        cli.set_lift_height(height=90.0, duration=1.0)
        time.sleep(1.2)

        print("Lowering lift...")
        cli.set_lift_height(height=32.0, duration=1.0)
        time.sleep(1.2)

        # --- Play a short built-in animation, if any are available ---
        # pycozmo loads Cozmo's built-in animation clips automatically when
        # it connects. get_anim_names() returns every clip name we could
        # pass to cli.play_anim(name). There are usually 900+ of them, with
        # cryptic internal names (e.g. "anim_greeting_happy_01") -- stage 2
        # will curate a short, kid-friendly list. For now we just grab
        # whichever one happens to have "happy" in its name, or fall back to
        # the very first one available, as a quick smoke test.
        anim_names = sorted(cli.get_anim_names())
        print(f"\n{len(anim_names)} built-in animations are available.")

        if anim_names:
            pick = next((n for n in anim_names if "happy" in n.lower()), anim_names[0])
            print(f"Playing animation: {pick}")
            cli.play_anim(pick)
            # Give the animation time to actually play before we disconnect.
            time.sleep(3.0)
        else:
            print("No animations loaded -- skipping animation playback.")

        print("\nConnection test complete. If Cozmo moved his head/lift and")
        print("played an animation, the WiFi + pycozmo connection is solid.")


if __name__ == "__main__":
    try:
        main()
    except pycozmo.exception.PyCozmoException as e:
        print(f"\nCozmo connection error: {e}")
        print("Double check this laptop's WiFi is connected to Cozmo's hotspot,")
        print("and that Cozmo is awake (not asleep/on charger with screen off).")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(0)
