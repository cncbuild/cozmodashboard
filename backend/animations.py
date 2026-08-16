"""
Curated list of Cozmo animations exposed as buttons in the UI.

Cozmo actually ships with ~1,000 raw animation clips (things like
"anim_greeting_happy_02"), most with cryptic internal names. This file picks
a kid-friendly subset and gives each one a friendly label, an emoji, and a
category -- this is the ONLY file you need to edit to add, rename, or remove
animation buttons. You don't need to touch the backend or frontend code.

To find more real animation names to add here, connect to Cozmo (or just run
this with no robot connected -- animation names are loaded from local files,
not from the robot) and run:

    from cozmo_service import CozmoService
    import pycozmo
    cli = pycozmo.Client(auto_initialize=False)
    cli.load_anims()
    for name in sorted(cli.get_anim_names()):
        print(name)

Each entry below is:
    "key": {
        "label": "Text shown on the button",
        "emoji": "Emoji shown on the button",
        "clip": "the real pycozmo animation clip name",
        "category": "Which group of buttons this appears under in the UI",
    }
"""

ANIMATIONS = {
    # --- Emotions ---
    "happy": {
        "label": "Happy",
        "emoji": "\U0001F600",
        "clip": "anim_greeting_happy_02",
        "category": "Emotions",
    },
    "giggle": {
        "label": "Giggle",
        "emoji": "\U0001F602",
        "clip": "anim_poked_giggle",
        "category": "Emotions",
    },
    "surprised": {
        "label": "Surprised",
        "emoji": "\U0001F632",
        "clip": "anim_reacttppl_surprise",
        "category": "Emotions",
    },
    "sleepy": {
        "label": "Sleepy",
        "emoji": "\U0001F634",
        "clip": "anim_gotosleep_getin_01",
        "category": "Emotions",
    },
    "bored": {
        "label": "Bored",
        "emoji": "\U0001F644",
        "clip": "anim_bored_01",
        "category": "Emotions",
    },
    "frustrated": {
        "label": "Frustrated",
        "emoji": "\U0001F620",
        "clip": "anim_reacttoblock_frustrated_01",
        "category": "Emotions",
    },
    "confused": {
        "label": "Confused",
        "emoji": "\U0001F615",
        "clip": "anim_gif_idk_01",
        "category": "Emotions",
    },
    "dizzy": {
        "label": "Dizzy",
        "emoji": "\U0001F635",
        "clip": "anim_dizzy_reaction_medium_01",
        "category": "Emotions",
    },

    # --- Reactions / tricks ---
    "celebrate": {
        "label": "Celebrate!",
        "emoji": "\U0001F389",
        "clip": "anim_majorwin",
        "category": "Reactions",
    },
    "success": {
        "label": "Yay!",
        "emoji": "\U0001F31F",
        "clip": "anim_reacttoblock_success_01",
        "category": "Reactions",
    },
    "fistbump": {
        "label": "Fist Bump",
        "emoji": "\U0001F44A",
        "clip": "anim_fistbump_requestonce_01",
        "category": "Reactions",
    },
    "peekaboo": {
        "label": "Peekaboo",
        "emoji": "\U0001F648",
        "clip": "anim_peekaboo_idle_01",
        "category": "Reactions",
    },
    "wiggle": {
        "label": "Wiggle",
        "emoji": "\U0001F483",
        "clip": "anim_freeplay_reacttoface_wiggle_01",
        "category": "Reactions",
    },
    "no": {
        "label": "No!",
        "emoji": "\U0001F645",
        "clip": "anim_gif_no_01",
        "category": "Reactions",
    },
    "sing": {
        "label": "Sing a Song",
        "emoji": "\U0001F3B5",
        "clip": "anim_cozmosings_80_song_01",
        "category": "Reactions",
    },

    # --- Animal impressions (Code Lab clips) ---
    "chicken": {
        "label": "Chicken",
        "emoji": "\U0001F414",
        "clip": "anim_codelab_chicken_01",
        "category": "Animals",
    },
    "cow": {
        "label": "Cow",
        "emoji": "\U0001F404",
        "clip": "anim_codelab_cow_01",
        "category": "Animals",
    },
    "duck": {
        "label": "Duck",
        "emoji": "\U0001F986",
        "clip": "anim_codelab_duck_01",
        "category": "Animals",
    },
    "elephant": {
        "label": "Elephant",
        "emoji": "\U0001F418",
        "clip": "anim_codelab_elephant_01",
        "category": "Animals",
    },
    "frog": {
        "label": "Frog",
        "emoji": "\U0001F438",
        "clip": "anim_codelab_frog_01",
        "category": "Animals",
    },
    "cat": {
        "label": "Cat",
        "emoji": "\U0001F431",
        "clip": "anim_petdetection_cat_01",
        "category": "Animals",
    },
}
