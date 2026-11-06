# Guard: presenting to guests

Run it paced (the default in the console), so you can talk for as long as you need at
each stage. Nothing moves on until someone presses Continue. A match lasts 5 to 20
seconds; the whole run, with take-off, the DJI and the finale, takes about 3 minutes.

**Two people:** the *operator* at the laptop presses Continue and narrates, and the
*pilot* flies the DJI. The show waits for the pilot twice: when the DJI goes up, and when
it comes down.

Before guests arrive, run the same choices in the simulator. Pick an even pairing (see
[how-it-works.md](how-it-works.md#the-strategies)); a match that is over in three
seconds is hard to narrate.

## The script

| Stage | Operator | Say |
|---|---|---|
| **Before** | | "The big drone is something we want to protect. The blue team defends it, the red team attacks it. Nobody flies them by hand: cameras around the room tell one laptop where everything is, and each team's strategy decides what to do, 20 times a second. The two teams can't read each other's plans; each only sees where the other team is." |
| **1. Take off** | Continue | "They go up and hold their places." |
| **2. DJI up** | pilot flies up, then Continue | "The pilot brings the VIP in. The small drones keep out of its way on their own." |
| **3. Start** | Continue | "From now on, nobody is steering." |
| **4. The match** | watch | Point at what the lights show: "Red is staging, spreading out round the VIP… now they go in together." "White means scoring: that defender is taking an attacker out." "Magenta is a decoy, sent in first to pull the defence over." |
| **5. The finale** | watch | Defence win: "They held: the honour guard." Attack win: "One got through. They've captured the VIP; watch them follow it." *Ask the pilot to drift the DJI slowly.* |
| **6. DJI down** | pilot lands, then Continue | "The VIP lands first, then the escort." |

The key line, if you only get one: **nobody tells the drones what to do. Each team has a
plan, and they play it against each other live; a safety layer underneath stops anyone
crashing, whatever the plans ask for.**

## Questions you will get

**"Is it pre-programmed?"** No. The strategies decide from where everyone is, 20 times a
second, and the same start gives a different match each time.

**"Who wins?"** It depends on the pairing and the rules. Some strategies beat others
nearly every time; the even pairings are the ones worth watching.

**"What stops a crash?"** A safety layer adjusts every command together, so no two
drones get too close and nobody flies into the VIP. Strategies can't switch it off. On
top of that, if two drones come too close anyway, the game pauses; much closer, and
everything lands.

**"Can the teams cheat?"** Each strategy only sees what the cameras see of the other
team, never its plan. That's enforced in the code, not left to good manners.

**"Could this work outdoors?"** Not as it is: it depends on the cameras. The strategies
and the safety layer don't care where positions come from.

## When something goes wrong, live

| What happened | Say |
|---|---|
| Everything stops in mid-air for a moment | "Two drones came close, so the game paused until they were apart. That's the safety net working." |
| Everything lands | "Something came too close, or a drone stopped following orders, so everything landed. That's the rule." |
| The attack wins in seconds | "That pairing favours the attack. Let's give the defence a better plan." |
| A drone never arms | "A firmware safety latch. It needs a battery re-plug, which is deliberate." |
| Nothing happens at all | "Give me a moment, this is a research rig." Then stop talking and fix it. |

## Claims to keep honest

- **"It can't crash"** is not true. Say the safety layer keeps them apart and lands them
  if anything gets too close.
- The strategies were checked over thousands of simulated matches. Only some pairings
  have flown on real drones.
- Today, the drones run about half a second behind their commands (see
  [how-it-works.md](how-it-works.md#why-the-drones-run-late-and-what-to-do-about-it)).
  Say "the safety margins are set for that", not "they move exactly where they're told".
- "I don't know, I can find out" is a good answer. Never upgrade a claim under pressure.
