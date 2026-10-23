"""Teto's idle life: a library of 100+ little animations and helpful moments.

Each Behavior is a short script of Steps. A step says how she looks (poses
cycled every `period` seconds), what she holds (props), what floats around
her (particles), how she moves (walk, hop, jump onto a window...), and maybe
something she says. Pure data + a chooser, no Tk, so it is unit-testable.
"""

from __future__ import annotations

import datetime as _dt
import random
from dataclasses import dataclass, field


def P(eyes: str = "open", mouth: str = "smile", arms: str = "down", body: str = "") -> dict:
    return {"eyes": eyes, "mouth": mouth, "arms": arms, "body": body}


@dataclass(frozen=True)
class Step:
    dur: float = 1.0
    poses: tuple = (P(),)
    period: float = 0.35
    props: tuple = ()               # prop names held this step, or a tuple of tuples to cycle
    prop_period: float = 0.35
    fx: tuple = ()                  # ((kind, per_second, anchor), ...)
    move: str = ""                  # see MOVES
    speed: float = 0.0
    say: tuple = ()                 # one line picked at random when the step starts


MOVES = {"", "walk", "run", "tiptoe", "moonwalk", "hop", "jump", "bigjump", "to_window", "float",
         "shake", "spin", "chase_cursor", "teleport", "dash", "bounce"}


@dataclass(frozen=True)
class Behavior:
    name: str
    steps: tuple
    weight: float = 1.0
    when: str = "any"               # see CONDITIONS
    cooldown: float = 120.0         # seconds before it may repeat
    tag: str = "idle"               # idle | helpful | seasonal
    task: str = ""                  # clicking her speech bubble asks her to do this

    @property
    def duration(self) -> float:
        return sum(s.dur for s in self.steps)


# ------------------------------------------------------------- helpers
def S(dur=1.0, *poses, period=0.35, props=(), prop_period=0.35, fx=(), move="", speed=0.0, say=()):
    if not poses:
        poses = (P(),)
    if isinstance(props, str):
        props = (props,)
    if isinstance(say, str):
        say = (say,)
    return Step(dur, tuple(poses), period, tuple(props), prop_period, tuple(fx), move, speed, tuple(say))


def B(name, *steps, weight=1.0, when="any", cooldown=120.0, tag="idle", task=""):
    return Behavior(name, tuple(steps), weight, when, cooldown, tag, task)


HAPPY = P("happy", "open")
HAPPY_UP = P("happy", "open", "up_both", "bob")
SMILE = P()
BOB = P(body="bob")
TALK = (P(mouth="open"), P())
CHEW = (P("happy", "chew"), P("happy", "smile", body="bob"))
SING = (P("closed", "open"), P("closed", "o", body="bob"))
WALK = (P(body="bob"), P())


def fx(kind, rate=2.0, at="head"):
    return (kind, rate, at)


# ------------------------------------------------------------ the library
LIBRARY: list[Behavior] = [
    # --- everyday little moments ---------------------------------------------------
    B("look_around", S(0.9, P("look_l")), S(0.9, P("look_r")), S(0.6, P("look_u")), S(0.5, SMILE), weight=3),
    B("double_blink", S(0.12, P("blink")), S(0.12, SMILE), S(0.12, P("blink")), S(1.2, SMILE), weight=2),
    B("yawn", S(1.4, P("closed", "yawn", "up_both", "stretch"), say=("Fwaaah~", "*yawn*")), S(0.6, P("sleepy"))),
    B("big_stretch", S(1.2, P("closed", "o", "up_both", "stretch"), say="Nnnn~ stretchy!"), S(0.4, BOB), S(0.6, SMILE)),
    B("sneeze", S(0.5, P("closed", "o", body="stretch")), S(0.3, P("closed", "open", body="squash"),
      fx=(fx("dust", 12, "mouth"),), say="Achoo!"), S(0.8, P("dizzy", "wobble"))),
    B("hiccup", *[S(0.6, P("wide", "o", body="stretch"), fx=(fx("bang", 2),), say=("hic!",) if i == 0 else ())
                  for i in range(3)], S(0.6, P("sad", "wobble"))),
    B("giggle", S(1.4, P("happy", "grin"), P("happy", "grin", body="bob"), period=0.15,
      fx=(fx("note", 1.5),), say=("Hehehe~", "Teehee!"))),
    B("sigh", S(1.2, P("sleepy", "flat", body="squash"), fx=(fx("steam", 2, "mouth"),), say="Haaa..."), S(0.4, SMILE)),
    B("nod", S(1.2, P(), P(body="bob"), period=0.2)),
    B("head_shake", S(1.0, P("closed", "flat", body="lean_l"), P("closed", "flat", body="lean_r"), period=0.18)),
    B("head_tilt", S(1.5, P(mouth="o", body="lean_l")), S(0.3, SMILE), S(1.2, P(body="lean_r"), say="Hm?")),
    B("wink", S(0.2, SMILE), S(0.8, P("wink", "grin"), fx=(fx("sparkle", 3),), say="☆")),
    B("hum", S(3.0, P("closed", "smile"), P("closed", "smile", body="bob"), period=0.45, fx=(fx("note", 1.5),),
      say=("Hmm hm hmmm~", "♪ La la la~"))),
    B("whistle", S(2.6, P("closed", "o"), P("closed", "o", body="bob"), period=0.5, fx=(fx("music_r", 1.5),))),
    B("daydream", S(3.0, P("look_u", "smile"), fx=(fx("cloud", 1, "above"), fx("heart", 0.6, "above")),
      say=("*daydreaming about bread*", "...ehehe~"))),
    B("deep_think", S(2.4, P("look_u", "flat", "point_r"), fx=(fx("dot", 3, "above"),)),
      S(0.8, P("star", "open", "up_r"), fx=(fx("bulb", 3, "above"),), say="Ah! I've got it!")),
    B("count_fingers", S(2.4, P("look_l", "o", "point_r"), P("look_l", "chew", "point_r"), period=0.5,
      say="One, two, three..."), S(0.6, P("happy", "open"))),
    B("tap_foot", S(2.2, P(), P(body="bob"), period=0.18, fx=(fx("tap", 4, "feet"),))),
    B("pout", S(2.0, P("angry", "frown"), fx=(fx("anger", 1),), say="Hmph!")),
    B("surprised", S(0.3, P("wide", "o", "up_both", "stretch"), fx=(fx("bang", 4),), move="jump", say="Eh?!"),
      S(0.8, P("look_l")), S(0.6, P("happy"))),
    B("shiver", S(2.0, P("closed", "wobble"), move="shake", fx=(fx("snow", 2),), say="B-brr..."), when="winter"),
    B("too_hot", S(2.4, P("sleepy", "tongue"), props="fan", fx=(fx("sweat", 2),), say="So hooot..."), when="summer"),
    B("hair_flip", S(0.4, P("closed", body="lean_l")), S(0.4, P("closed", body="lean_r")),
      S(0.8, P("wink", "grin"), fx=(fx("sparkle", 4),), say="Drills: perfect ✓")),
    B("mirror_check", S(1.2, P("look_l"), props="phone"), S(1.0, P("happy", "grin"), props="phone",
      say="Looking cute today~")),
    B("peekaboo", S(1.0, P("closed", "flat", "up_both")), S(0.6, P("wide", "open", "up_both", "stretch"),
      fx=(fx("sparkle", 6),), say="Peekaboo!"), S(0.6, HAPPY)),
    B("bow", S(0.8, P("closed", body="squash")), S(0.6, SMILE, say="*bows politely*")),
    B("salute", S(1.4, P("wide", "flat", "up_r"), say="Teto, reporting for duty!")),
    B("peace_sign", S(1.4, P("wink", "grin", "up_r"), fx=(fx("star", 2),), say="✌ Peace!")),
    B("heart_hands", S(1.6, P("happy", "smile", "up_both"), fx=(fx("heart", 4, "above"),), say="Love you, user~")),

    # --- movement ------------------------------------------------------------------
    B("stroll", S(4.0, *WALK, period=0.25, move="walk", speed=80), S(0.6, SMILE), weight=4, cooldown=20),
    B("tiptoe", S(3.0, P("look_l", "o"), P("look_l", "o", body="bob"), period=0.3, move="tiptoe", speed=35,
      say="Sneak... sneak..."), S(0.5, P("wink"))),
    B("zoomies", S(1.6, P("happy", "open", body="bob"), P("happy", "open"), period=0.1, move="run", speed=320,
      fx=(fx("dust", 6, "feet"),), say="Zoomies!!"), S(1.6, P("happy", "open"), period=0.1, move="run", speed=-320),
      S(0.6, P("dizzy", "wobble"))),
    B("moonwalk", S(3.0, P("closed", "grin"), P("closed", "grin", body="bob"), period=0.25, move="moonwalk",
      speed=70, fx=(fx("sparkle", 1.5, "feet"),), say="Hee-hee!")),
    B("skip", S(3.2, P("happy", "smile"), period=0.3, move="hop", speed=110, fx=(fx("note", 1.2),))),
    B("bunny_hops", S(2.6, P("happy", "o"), period=0.3, move="hop", speed=0)),
    B("jump_for_joy", S(0.4, P("happy", "open", body="squash")), S(1.2, HAPPY_UP, move="jump",
      fx=(fx("sparkle", 6),), say="Yay!")),
    B("big_jump", S(0.5, P("closed", "flat", body="squash")), S(1.4, P("wide", "open", "up_both"),
      move="bigjump", say="Hup!")),
    B("climb_window", S(0.5, P("look_u", "o", body="squash"), say="Ooh, a window!"), S(1.6, P("wide", "open",
      "up_both"), move="to_window"), S(0.8, HAPPY, say=("Nice view!", "King of the window~"))),
    B("backflip", S(0.4, P("closed", "flat", body="squash")), S(0.15, P("closed", "o", "up_both"), move="bigjump"),
      S(0.15, P("closed", "o", body="rot90")), S(0.15, P("closed", "o", body="rot180")),
      S(0.15, P("closed", "o", body="rot270")), S(0.8, HAPPY_UP, fx=(fx("star", 5),), say="Ta-da!")),
    B("cartwheel", *[S(0.18, P("happy", "open", "up_both", b), move="walk", speed=180)
                     for b in ("", "rot90", "rot180", "rot270", "")], S(0.7, HAPPY_UP, say="Wheee!")),
    B("handstand", S(2.0, P("happy", "o", body="upside"), say="Look! No hands... wait."), S(0.6, P("dizzy"))),
    B("spin", S(1.6, P("happy", "open"), period=0.12, move="spin", fx=(fx("sparkle", 4),)), S(0.8, P("dizzy", "wobble"))),
    B("chase_cursor", S(3.5, P("look_r", "open"), P("look_r", "open", body="bob"), period=0.2, move="chase_cursor",
      speed=170, say="Hey, wait up, cursor!"), S(0.6, HAPPY)),
    B("teleport", S(0.6, P("closed", "o", "up_both"), fx=(fx("sparkle", 10),), say="Teto... teleport!"),
      S(0.5, P("closed", "o"), move="teleport", fx=(fx("flash", 6),)), S(0.8, P("star", "open"), say="Ta-dah!")),
    B("dash", S(1.2, P("wide", "open"), period=0.1, move="dash", speed=380, fx=(fx("dust", 8, "feet"),)),
      S(0.5, P("dizzy"))),
    B("float", S(3.0, P("closed", "smile", "up_both"), move="float", fx=(fx("sparkle", 2, "feet"),),
      say="I'm floating~")),
    B("trip", S(1.0, *WALK, period=0.2, move="walk", speed=100), S(0.6, P("wide", "open", body="lie_l"),
      fx=(fx("dust", 10, "feet"),), say="Waah!"), S(1.0, P("dizzy", "wobble", body="lie_l"),
      fx=(fx("star", 3, "head"),)), S(0.6, P("sad", "flat"), say="I'm okay...")),

    # --- music & dance (she's a singer after all) -------------------------------------------
    B("sing", S(4.0, *SING, period=0.4, props="mic", fx=(fx("note", 2.5), fx("music_r", 1.5)),
      say=("♪ Kasane Territory~", "♪ Do-re-mi-fa-so~", "♪ Fukkireta~!")), weight=2),
    B("karaoke", S(1.2, P("closed", "open", "up_l"), props="mic", say="This one's for you!"),
      S(3.0, *SING, period=0.3, props="mic", fx=(fx("note", 3), fx("sparkle", 1)))),
    B("dance", S(4.0, P("happy", "open", "up_both", "lean_l"), P("happy", "open", "up_both", "lean_r"),
      period=0.3, move="hop", fx=(fx("note", 2),), say="Dance time!"), weight=2),
    B("robot_dance", S(3.2, P("wide", "flat", "point_r"), P("wide", "flat", "point_l"), P("wide", "flat", "up_both"),
      period=0.35, fx=(fx("gear", 1.5),), say="BEEP. BOOP.")),
    B("guitar", S(4.0, P("closed", "open"), P("closed", "grin", body="bob"), period=0.25, props="guitar",
      fx=(fx("music_r", 3),), say="Rock on!")),
    B("drums", S(3.2, P("angry", "grin", "up_both"), P("angry", "grin", body="bob"), period=0.12,
      props=(("drumstick",), ()), prop_period=0.12, fx=(fx("bang", 3),), say="Ba-dum-tss!")),
    B("conduct", S(3.2, P("closed", "o", "up_r"), P("closed", "o", "point_r"), period=0.4, props="baton",
      fx=(fx("note", 2),))),
    B("maracas", S(3.0, P("happy", "open", "up_both"), P("happy", "grin", "up_both", "bob"), period=0.15,
      props=("maracas", "maracas_l"), fx=(fx("note", 2),), say="Cha-cha-cha!")),
    B("dj", S(4.0, P("closed", "grin"), P("closed", "grin", body="bob"), period=0.25, props="headphones",
      fx=(fx("music_r", 2), fx("note", 2)), say="Drop the beat~")),
    B("beatbox", S(3.0, P("closed", "o"), P("closed", "grin", body="bob"), period=0.15, fx=(fx("bang", 2, "mouth"),),
      say="Boots-n-cats-n...")),
    B("ballet", S(3.0, P("closed", "smile", "up_both", "stretch"), period=0.3, move="spin",
      fx=(fx("petal", 2),))),
    B("pompoms", S(3.0, P("happy", "open", "up_both"), P("happy", "open", "down", "bob"), period=0.25,
      props=("pompom", "pompom_l"), move="hop", say="Go, user, go!")),

    # --- food (bread first, always) -----------------------------------------------
    B("eat_bread", S(0.8, P("star", "open"), props="bread", say=("Bread time!", "Baguette~♪")),
      S(3.0, *CHEW, period=0.25, props="bread", fx=(fx("crumb", 6, "mouth"),)),
      S(0.8, P("happy", "smile"), fx=(fx("heart", 3),), say="Delicious!"), weight=2.5),
    B("bread_hug", S(2.4, P("heart", "smile"), props="bread", fx=(fx("heart", 3),), say="My precious bread...")),
    B("tea_time", S(3.4, P("closed", "smile"), P("closed", "o"), period=0.8, props="cup",
      fx=(fx("steam", 1.5, "hand_r"),), say="Tea time~"), when="afternoon"),
    B("morning_coffee", S(3.4, P("sleepy", "o"), P("sleepy", "smile"), period=0.8, props="mug",
      fx=(fx("steam", 1.5, "hand_r"),), say="Coffee... coffee first..."), when="morning", weight=2),
    B("onigiri", S(3.0, *CHEW, period=0.25, props="onigiri", say="Onigiri!")),
    B("ice_cream", S(3.2, P("happy", "tongue"), P("happy", "smile"), period=0.3, props="icecream",
      say="Mmm, strawberry!"), when="summer", weight=1.5),
    B("lollipop", S(3.0, P("closed", "tongue"), P("closed", "smile"), period=0.4, props="lollipop")),
    B("bubble_gum", S(0.6, P(mouth="chew")), S(0.5, P("look_u", "o"), props="gum1"),
      S(0.5, P("wide", "o"), props="gum2"), S(0.5, P("wide", "o"), props="gum3"),
      S(0.7, P("dizzy", "open", body="squash"), fx=(fx("flash", 8, "mouth"),), say="*POP*")),
    B("hungry", S(2.0, P("sad", "o"), fx=(fx("question", 1),), say="*stomach growls* ...bread?")),

    # --- hobbies ---------------------------------------------------------------------
    B("read_book", S(4.0, P("look_l", "smile"), P("blink", "smile"), period=1.2, props="book",
      say=("Ooh, a plot twist!", "Just one more chapter...")), weight=1.5),
    B("write_notes", S(3.2, P("look_l", "flat"), P("look_l", "chew"), period=0.5, props="notebook",
      fx=(fx("tap", 3, "hand_r"),), say="Taking notes~")),
    B("game_time", S(4.0, P("angry", "grin"), P("angry", "o", body="bob"), period=0.2, props="gamepad",
      fx=(fx("star", 1.5),)), S(0.8, HAPPY_UP, say="New high score!")),
    B("check_phone", S(3.0, P("look_l", "smile"), P("blink", "o"), period=0.9, props="phone",
      say="*scrolling*")),
    B("selfie", S(0.8, P("wink", "grin", "up_r"), props="camera"), S(0.4, P("wink", "grin", "up_r"),
      props="camera", fx=(fx("flash", 10, "hand_r"),), say="Say bread!")),
    B("paint", S(3.4, P("look_l", "o"), P("look_l", "smile", body="bob"), period=0.4, props="brush",
      fx=(fx("confetti_r", 3, "hand_r"), fx("confetti_b", 3, "hand_r")), say="A masterpiece!")),
    B("sweep", S(3.4, P("closed", "flat", body="lean_l"), P("closed", "flat", body="lean_r"), period=0.35,
      props="broom", move="walk", speed=40, fx=(fx("dust", 5, "feet"),), say="Tidying up your desktop~")),
    B("water_plant", S(1.0, P(), props=("can", "plant")), S(2.4, P("happy", "o"), props=("can", "plant"),
      fx=(fx("drop", 6, "hand_r"),)), S(1.2, HAPPY, props="plant_big", fx=(fx("sparkle", 4, "feet"),),
      say="It grew!")),
    B("juggle", S(3.4, P("look_u", "o", "up_both"), P("look_u", "o", "up_both", "bob"), period=0.2,
      fx=(fx("juggle_r", 2.5, "above"), fx("juggle_y", 2.5, "above"), fx("juggle_b", 2.5, "above")),
      say="Watch this!")),
    B("yoyo", S(3.0, P("look_l", "o"), period=0.3, props=(("yoyo_up",), ("yoyo_down",)), prop_period=0.3)),
    B("fishing", S(1.0, P("closed", "flat"), props="rod"), S(2.4, P("look_r", "flat"), props="rod",
      fx=(fx("bubble", 1, "ground_r"),)), S(1.2, P("star", "open", "up_r"), props="rod", fx=(fx("fish", 4, "ground_r"),),
      say="I caught one!")),
    B("kite", S(4.0, P("look_u", "open", "up_r"), props="kite", move="walk", speed=60, fx=(fx("leaf", 1, "above"),)),
      when="spring"),
    B("balloon", S(3.4, P("look_u", "smile", "up_r"), props="balloon", say="Don't float away..."), weight=1.2),
    B("heart_balloon", S(3.0, P("heart", "smile", "up_r"), props="heart_balloon", fx=(fx("heart", 1),))),
    B("flower_sniff", S(2.6, P("closed", "smile"), props="flower", fx=(fx("petal", 2, "hand_r"),),
      say="Smells nice~"), when="spring", weight=1.5),
    B("stargaze", S(3.6, P("look_u", "o"), props="telescope", fx=(fx("star", 2, "above"),),
      say="Is that... a bread-shaped constellation?"), when="night"),
    B("bubbles", S(3.2, P("closed", "o"), fx=(fx("bubble", 3, "mouth"),), say="Bubbles~")),
    B("paper_plane", S(0.8, P("look_r", "o", "point_r")), S(1.6, P("star", "open", "point_r"),
      fx=(fx("plane", 1.5, "hand_r"),), say="Fly!")),
    B("magic_trick", S(1.2, P("wink", "grin"), props="wand", fx=(fx("sparkle", 5, "hand_r"),),
      say="Abracadabra..."), S(1.2, HAPPY, props="bread", fx=(fx("flash", 6, "hand_r"),), say="...BREAD!")),
    B("workout", S(3.0, P("angry", "flat", "up_both"), P("angry", "o", "down", "squash"), period=0.4,
      props="dumbbell", fx=(fx("sweat", 2),), say=("One! Two!", "Feel the burn!"))),
    B("jumping_jacks", S(3.0, P("closed", "o", "up_both", "stretch"), P("closed", "flat", "down", "squash"),
      period=0.3, move="hop", say="Jumping jacks!")),
    B("push_ups", S(3.0, P("angry", "flat", body="lie_l"), P("angry", "o", body="lie_l"), period=0.5,
      fx=(fx("sweat", 1.5),), say="...thirty-one... thirty-two...")),
    B("yoga", S(3.6, P("closed", "smile", "up_both", "stretch"), fx=(fx("sparkle", 1),), say="Namaste~")),
    B("meditate", S(4.0, P("closed", "flat", body="squash"), move="float", fx=(fx("sparkle", 1.2, "around"),),
      say="Ommmm...")),
    B("knit_time", S(3.0, P("look_l", "smile"), P("blink", "smile"), period=0.6, props="pencil",
      say="Drawing you a doodle!")),
    B("sparkler", S(3.0, P("star", "open", "up_r"), props="sparkler", fx=(fx("sparkle", 6, "hand_r_up"),)),
      when="summer"),
    B("snowball", S(1.2, P("look_r", "grin"), props="snowball"), S(0.6, P("wink", "open", "point_r"),
      fx=(fx("snow", 8, "hand_r"),), say="Snowball fight!"), when="winter"),
    B("umbrella", S(4.0, P("look_u", "smile"), props="umbrella", fx=(fx("rain", 8, "above"),),
      say="Pitter-patter~")),
    B("kick_ball", S(1.0, P("look_r", "o"), props="ball"), S(0.5, P("star", "open", body="lean_r"), props="ball",
      move="jump"), S(0.8, HAPPY, say="Goal!")),

    # --- friends ---------------------------------------------------------------------
    B("cat_visit", S(1.2, P("look_r", "o"), props=(("cat",), ("cat_blink",)), prop_period=0.7, say="A kitty!"),
      S(2.4, P("heart", "cat"), props=(("cat",), ("cat_blink",)), prop_period=0.7, fx=(fx("heart", 2, "ground_r"),),
        say="Nyaa~ ♪")),
    B("bird_friend", S(3.2, P("look_u", "smile"), props="bird", fx=(fx("note", 1.5, "head"),),
      say="Tweet tweet~")),
    B("butterfly", S(3.4, P("look_u", "open"), P("look_r", "open"), period=0.6, move="walk", speed=60,
      fx=(fx("butterfly", 1.5, "above"), fx("butterfly2", 1.5, "above")), say="Butterfly!")),
    B("wave_hello", S(1.8, P("happy", "open", "wave_r"), P("happy", "open", "up_r"), period=0.25,
      say=("Hiii!", "Hello hello~"))),

    # --- feelings --------------------------------------------------------------------
    B("cry_a_bit", S(2.0, P("cry", "frown"), fx=(fx("tear", 3, "eyes"),), say="The bread... it's all gone..."),
      S(1.0, P("happy", "smile"), say="Just kidding!"), weight=0.5),
    B("love", S(2.6, P("heart", "smile"), fx=(fx("heart", 3),), say="I'm happy you're here~")),
    B("cool", S(2.6, P("open", "grin", body="lean_r"), props="sunglasses", fx=(fx("sparkle", 1.5),),
      say="Deal with it.")),
    B("proud", S(2.2, P("closed", "grin", "up_both", "stretch"), props="crown", fx=(fx("star", 2),),
      say="Teto is the best!")),
    B("scared", S(1.6, P("wide", "wobble"), move="shake", fx=(fx("sweat", 3),), say="W-what was that?!"),
      S(0.8, P("look_l"))),
    B("laugh", S(1.0, P("happy", "grin"), period=0.12), S(1.6, P("happy", "grin", body="lie_r"),
      P("happy", "open", body="lie_r"), period=0.15, say="Ahahaha!"), S(0.5, HAPPY)),
    B("bored", S(2.6, P("sleepy", "flat", body="squash"), say="Soooo bored~"), S(0.4, P("look_u")),
      weight=0.6),
    B("excited", S(2.0, P("star", "open", "up_both"), P("star", "open", "up_both", "bob"), period=0.12,
      move="hop", fx=(fx("sparkle", 6),), say="Eeee!")),

    # --- naps ------------------------------------------------------------------------
    B("doze_off", S(1.6, P("sleepy", "flat")), S(0.4, P("closed", "flat", body="bob")),
      S(0.4, P("wide", "o"), say="I'm awake!"), when="afternoon"),
    B("nap", S(0.8, P("sleepy", "yawn"), say="Just a little nap..."), S(6.0, P("closed", "o", body="lie_r"),
      P("closed", "smile", body="lie_r"), period=1.4, props="pillow", fx=(fx("z", 0.8, "above"),)),
      S(1.0, P("sleepy", "yawn", "up_both", "stretch"), say="Fwaa~ refreshed!"), when="night", weight=1.5),
    B("power_nap", S(4.0, P("closed", "o", body="squash"), P("closed", "smile", body="squash"), period=1.2,
      fx=(fx("z", 1, "above"),)), S(0.6, P("wide", "o"), say="Huh? Was I sleeping?")),

    # --- time & seasons --------------------------------------------------------------
    B("good_morning", S(2.2, P("happy", "open", "up_both", "stretch"), fx=(fx("sparkle", 3),),
      say=("Good morning! Let's have a great {day}!", "Morning~ Did you sleep well?")), when="morning",
      cooldown=10800, tag="helpful"),
    B("lunch_bell", S(2.4, P("star", "open"), props="bread", fx=(fx("note", 2),),
      say="It's lunchtime! Don't skip it~"), when="noon", cooldown=10800, tag="helpful"),
    B("good_evening", S(2.2, P("closed", "smile"), fx=(fx("star", 1, "above"),),
      say="Evening already~ You worked hard today!"), when="evening", cooldown=10800, tag="helpful"),
    B("go_to_bed", S(2.6, P("sleepy", "yawn"), fx=(fx("z", 1, "above"),),
      say="It's {time}... maybe it's time to sleep?"), when="late", cooldown=3600, tag="helpful"),
    B("tell_time", S(2.4, P("open", "o"), props="clock", say="It's {time}!"), when="hourly", cooldown=3000,
      tag="helpful", weight=4),
    B("weekend", S(2.4, HAPPY_UP, move="hop", fx=(fx("confetti_y", 4, "above"),), say="It's the weekend~!"),
      when="weekend", cooldown=21600),
    B("friday", S(2.4, HAPPY_UP, move="hop", fx=(fx("note", 3),), say="Friday! Almost there~"), when="friday",
      cooldown=21600),
    B("rainy_mood", S(3.0, P("look_u", "flat"), props="umbrella", fx=(fx("rain", 10, "above"),),
      say="Cozy rainy-day vibes..."), when="autumn"),
    B("falling_leaves", S(3.0, P("look_u", "o"), fx=(fx("leaf", 3, "above"),), say="Autumn leaves~"),
      when="autumn"),
    B("snow_day", S(3.0, P("star", "open", "up_both"), fx=(fx("snow", 4, "above"),), say="It's snowing!"),
      when="winter"),
    B("cherry_blossoms", S(3.0, P("closed", "smile"), fx=(fx("petal", 4, "above"),), say="Sakura season~"),
      when="spring"),
    B("birthday", S(1.0, P("star", "open"), props=("party_hat", "cake")), S(3.0, HAPPY_UP,
      props=("party_hat", "cake"), move="hop", fx=(fx("confetti_r", 5, "above"), fx("confetti_y", 5, "above")),
      say="It's my birthday! I'm 31... in chimera years!"), when="april1", cooldown=3600, tag="seasonal", weight=5),
    B("april_fools", S(2.0, P("wink", "grin"), say="Did you know Teto started as an April Fools' joke? Hehe~"),
      when="april1", cooldown=7200, tag="seasonal", weight=3),
    B("halloween", S(3.0, P("wink", "grin"), props=("witch_hat", "pumpkin"), fx=(fx("bang", 1),),
      say="Trick or bread!"), when="halloween", cooldown=1800, tag="seasonal", weight=5),
    B("christmas", S(3.0, P("happy", "open"), props=("santa_hat", "gift"), fx=(fx("snow", 3, "above"),),
      say="Merry Christmas~!"), when="christmas", cooldown=1800, tag="seasonal", weight=5),
    B("new_year", S(3.0, HAPPY_UP, props="party_hat", fx=(fx("firework_r", 2, "above"), fx("firework_y", 2, "above"),
      fx("firework_b", 2, "above")), say="Happy New Year!"), when="newyear", cooldown=1800, tag="seasonal",
      weight=5),
    B("valentine", S(3.0, P("heart", "smile"), props="sign_heart", fx=(fx("heart", 4),),
      say="Happy Valentine's~"), when="valentine", cooldown=3600, tag="seasonal", weight=5),
    B("flower_crown", S(3.0, P("closed", "smile"), props="flower_crown", fx=(fx("petal", 2),)), when="spring"),

    # --- helpful moments (click her bubble to accept) -------------------------------------------
    B("hydrate", S(2.6, P("happy", "open"), props="bottle", fx=(fx("drop", 2, "hand_r"),),
      say="Water break! Have a sip, okay?"), cooldown=5400, tag="helpful", weight=3),
    B("stretch_break", S(2.8, P("closed", "o", "up_both", "stretch"), say="Time to stretch! Up, up~"),
      cooldown=3600, tag="helpful", weight=3),
    B("eye_rest", S(2.8, P("closed", "smile"), say="Rest your eyes: look at something far away for 20 seconds~"),
      cooldown=2400, tag="helpful", weight=3),
    B("posture", S(2.2, P("wide", "o", body="stretch"), say="Posture check! Sit up straight~"), cooldown=4800,
      tag="helpful", weight=2),
    B("offer_help", S(2.4, P("happy", "open", "wave_r"), say="Need a hand with anything? Click me!"),
      cooldown=2700, tag="helpful", weight=2),
    B("suggest_downloads", S(2.6, P("open", "o", "point_r"), props="broom",
      say="Want me to check what's filling up your Downloads folder? (click me)"),
      cooldown=21600, tag="helpful", task="Look in my Downloads folder and tell me what's using the most space. "
      "Don't delete or move anything."),
    B("suggest_weather", S(2.4, P("look_u", "o"), props="umbrella",
      say="Shall I check today's weather for you? (click me)"), when="morning", cooldown=21600, tag="helpful",
      task="Open the web browser, search for today's weather where I am, and tell me the forecast."),
    B("suggest_focus", S(2.4, P("open", "smile"), props="clock",
      say="Want me to set a 25-minute focus timer? (click me)"), cooldown=21600, tag="helpful",
      task="Open the Windows Clock app and start a 25-minute focus timer for me."),
    B("suggest_cleanup_desktop", S(2.4, P("open", "o"), props="broom",
      say="Want me to tell you which desktop files you haven't opened in months? (click me)"),
      cooldown=43200, tag="helpful", task="List the files on my Desktop I haven't modified in over 3 months. "
      "Don't change anything."),
    B("suggest_music", S(2.4, P("closed", "smile"), props="headphones",
      say="Want some music? I can open a lo-fi playlist! (click me)"), when="afternoon", cooldown=21600,
      tag="helpful", task="Open YouTube in the browser and play a lo-fi study music playlist."),
    B("compliment", S(2.4, P("happy", "smile"), fx=(fx("sparkle", 2),),
      say=("You're doing great today!", "I believe in you~", "Proud of you, user!")), cooldown=3600,
      tag="helpful", weight=2),
    B("fun_fact", S(3.0, P("star", "open", "up_r"),
      say=("Fun fact: my drills are not, in fact, actual drills.", "Fun fact: honey never spoils!",
           "Fun fact: octopuses have three hearts!", "Fun fact: bread is the best food. That's just science.",
           "Fun fact: a group of flamingos is called a 'flamboyance'!")), cooldown=1800, tag="helpful"),
    # --- extra-expressive arm movement -----------------------------------------------
    B("big_wave", S(2.4, P("happy", "open", "wave_r"), P("happy", "open", "up_r"), period=0.18,
      fx=(fx("sparkle", 1.5),), say=("Heeey! Over here~", "Hi hi hiii!")), weight=2),
    B("cheer_jump", S(0.4, P("happy", "o", "down", "squash")),
      S(1.6, P("star", "open", "cheer"), move="jump", fx=(fx("sparkle", 6), fx("star", 2, "above")),
        say=("You can do it!", "Woohoo!")), weight=2),
    B("arms_out_spin", S(2.0, P("happy", "open", "out_both"), period=0.12, move="spin",
      fx=(fx("sparkle", 3),), say="Wheee~"), S(0.5, P("dizzy", "open", "out_both"))),
    B("stretch_arms", S(1.0, P("sleepy", "o", "up_both", "stretch")),
      S(0.8, P("closed", "smile", "out_both")), S(0.8, P("happy", "smile", "hips"), say="Nnngh~ good stretch!")),
    B("flex", S(1.2, P("angry", "grin", "up_both"), P("angry", "grin", "up_both", "bob"), period=0.2,
      fx=(fx("anger", 1, "above"),), say="Teto is STRONG!"), S(0.8, P("happy", "grin", "hips"))),
    B("hands_on_hips", S(2.0, P("open", "smile", "hips"), P("open", "smile", "hips", "lean_l"),
      P("open", "smile", "hips", "lean_r"), period=0.5, say="Hmm, what shall we do next?")),
    B("clap", S(2.2, P("happy", "open", "clap_a"), P("happy", "grin", "clap_b"), period=0.18,
      fx=(fx("note", 1.5),), say=("Yay yay yay!", "*clap clap clap*")), weight=1.5),
    B("conduct_big", S(3.0, P("closed", "o", "out_r"), P("closed", "o", "up_r"), P("closed", "o", "out_l"),
      P("closed", "o", "up_l"), period=0.3, props="baton", fx=(fx("note", 2),), say="And a-one, a-two~")),
    B("ta_da", S(0.5, P("closed", "flat", "down", "squash")),
      S(1.6, P("star", "open", "out_both", "stretch"), fx=(fx("sparkle", 7), fx("star", 3, "above")),
        say="Ta-daaa! ☆")),
    B("shrug", S(1.8, P("sleepy", "flat", "out_both"), say=("Eh, who knows~", "Beats me!"))),
    B("point_dance", S(2.8, P("wink", "grin", "point_r"), P("wink", "grin", "point_l"), period=0.25,
      move="hop", fx=(fx("note", 1.5),), say="Stayin' alive~")),
    B("reach_up", S(2.0, P("look_u", "o", "up_both"), P("look_u", "o", "up_both", "stretch"), period=0.4,
      fx=(fx("sparkle", 1, "above"),), say="Juuust a little higher...")),
    B("hug_offer", S(2.6, P("happy", "smile", "out_both"), fx=(fx("heart", 2),),
      say=("Hug? ♪", "C'mere, you~")), weight=1.5),
    B("disco", S(3.2, P("wink", "grin", "up_r"), P("wink", "grin", "point_r"), P("happy", "grin", "up_l"),
      P("happy", "grin", "point_l"), period=0.22, move="hop", fx=(fx("music_r", 2), fx("sparkle", 1)),
      say="Disco Teto!"), weight=1.5),
    B("wave_both", S(2.2, P("happy", "open", "cheer"), P("happy", "open", "up_both"), period=0.2,
      say="Byeee~ ...just kidding, I'm staying!")),
    B("present", S(0.6, P("wink", "grin", "out_r")),
      S(2.0, P("happy", "open", "out_both"), props="bread", fx=(fx("sparkle", 3, "hand_r"),),
        say="Tada! Fresh bread, just for you~")),
    B("march", S(3.0, P("open", "flat", "swing_a"), P("open", "flat", "swing_b"), period=0.3,
      move="walk", speed=70, say="Left, right, left!")),
    B("stretch_side", S(1.2, P("closed", "smile", "up_l", "lean_r")),
      S(1.2, P("closed", "smile", "up_r", "lean_l"), say="Side to side~")),
    B("joke", S(2.6, P("wink", "grin"), say=("Why did the bread break up? It felt kneaded too much!",
      "What do you call a sleeping bread? A loaf-nap!", "I told my computer a joke... it didn't get it. Bit sad.")),
      S(0.8, P("happy", "grin"), fx=(fx("note", 2),)), cooldown=1800, tag="helpful"),
]

# --------------------------------------------------------------- choosing
CONDITIONS = ("any", "morning", "noon", "afternoon", "evening", "night", "late", "hourly", "weekend", "friday",
              "april1", "halloween", "christmas", "newyear", "valentine", "winter", "spring", "summer", "autumn")


def condition_met(when: str, now: _dt.datetime) -> bool:
    h, m, mo, d, wd = now.hour, now.minute, now.month, now.day, now.weekday()
    return {
        "any": True,
        "morning": 6 <= h < 11,
        "noon": 11 <= h < 14,
        "afternoon": 14 <= h < 18,
        "evening": 18 <= h < 22,
        "night": h >= 21 or h < 6,
        "late": h >= 23 or h < 4,
        "hourly": m < 3,
        "weekend": wd >= 5,
        "friday": wd == 4,
        "april1": mo == 4 and d == 1,
        "halloween": mo == 10 and d >= 25,
        "christmas": mo == 12 and 18 <= d <= 26,
        "newyear": (mo == 12 and d == 31) or (mo == 1 and d <= 2),
        "valentine": mo == 2 and d == 14,
        "winter": mo in (12, 1, 2),
        "spring": mo in (3, 4, 5),
        "summer": mo in (6, 7, 8),
        "autumn": mo in (9, 10, 11),
    }.get(when, False)


def fill(text: str, now: _dt.datetime) -> str:
    return (text.replace("{time}", now.strftime("%H:%M"))
                .replace("{day}", now.strftime("%A"))
                .replace("{date}", now.strftime("%B %d").replace(" 0", " ")))


@dataclass
class Chooser:
    """Picks the next idle behaviour: weighted, time-aware, no quick repeats."""
    rng: random.Random = field(default_factory=random.Random)
    last_run: dict = field(default_factory=dict)
    recent: list = field(default_factory=list)
    helpful: bool = True

    def pick(self, now: _dt.datetime, clock: float, library: list[Behavior] | None = None) -> Behavior:
        lib = library if library is not None else LIBRARY
        options, weights = [], []
        for b in lib:
            if not condition_met(b.when, now):
                continue
            if b.tag == "helpful" and not self.helpful:
                continue
            if clock - self.last_run.get(b.name, -1e9) < b.cooldown or b.name in self.recent[-6:]:
                continue
            w = b.weight * (2.0 if b.when != "any" else 1.0)
            options.append(b)
            weights.append(w)
        if not options:
            options = [b for b in lib if b.when == "any" and b.tag == "idle"] or list(lib)
            weights = [b.weight for b in options]
        choice = self.rng.choices(options, weights=weights, k=1)[0]
        self.last_run[choice.name] = clock
        self.recent.append(choice.name)
        del self.recent[:-12]
        return choice


def by_name(name: str) -> Behavior:
    for b in LIBRARY:
        if b.name == name:
            return b
    raise KeyError(name)
