# Escort: presenting to guests

The show is operator-paced, so you can talk for as long as you need at each stage.
Nothing moves on until Enter is pressed. A full run takes about 4 to 6 minutes.

**Two people:** the *operator* at the laptop presses Enter (and can narrate), and the
*pilot* flies the DJI. Agree beforehand who says "bring it up" and "bring it down". Those
are the only two moments when the show waits for the pilot instead of the operator.

## The script

| Stage | Operator | Say |
|---|---|---|
| **Before** | | "This DJI stands in for something we want to protect. These three small drones are its escort, and this fourth one will try to reach it. None of them can see each other: cameras around the room tell one computer where everything is, 50 times a second. And the DJI is flown by hand, so nothing here is rehearsed." |
| **1. Take off** | Enter | "The escort goes up first and waits *above* where the DJI will be, out of its way." |
| **2. DJI up** | pilot flies up, then Enter | "Now they drop down and lock on. Wherever the pilot flies it, the ring follows." *A good moment to let the pilot drift around.* |
| **3. Station** | Enter | "The fourth drone is the threat. It is amber: sizing up the formation, not committed yet." |
| **4. Attack** | Enter | "Now it is red and going for the DJI. It is not following a script: it looks for the widest gap and goes for it. The defenders react: the nearest one turns white and gets in the way, and the other two close up beside it." |
| **5. Stand down** | Enter | "It has run out of options and is backing off. That is the magenta. Nobody told it to give up." |
| **6. DJI down** | Enter, pilot lands, Enter | "The escort climbs out of the way while the DJI lands. They come down last, so the thing being protected is never left alone in the air." |

The key line, if you only get one: **the attacker is as fast as the defenders, but they
fly a tighter circle, so they cover the same angle in less distance. They win on
geometry, not speed.**

![What the lights mean](../diagrams/11-light-legend.png)

If the whole fleet goes **amber**, the show is waiting for someone. If the defenders go
**cyan**, the DJI left its box: the pilot flies back toward the middle and they resume.

## Questions you will get

**"Is it pre-programmed?"** The defence is not: it works out where the threat is 20 times a
second. Move the DJI and the whole ring follows and re-aims.

**"What stops a crash?"** Minimum distances are enforced on every command before it
leaves the laptop. There is also a geofence, automatic landing if the cameras lose a
drone, and a one-click emergency stop.

**"Could it get through?"** Yes, if it were fast enough (about 1 m/s here, against the
0.6 m/s it flies) or if the DJI moves during the attack. We know roughly where that line is.

**"Do the defenders push it away?"** No. They hold their line, and the attacker is the
one that keeps its distance. Nobody touches anybody.

**"Would this work outdoors?"** Not as it is: it depends on the cameras. What carries
over is the behaviour: turning the ring, picking the blocker, and the safety rules.

**"How does it know where everything is?"** Motion-capture cameras track reflective
markers. All decisions are made on this laptop and sent out over one radio.

More answers, sorted by audience: [details/escort-qna.md](../details/escort-qna.md).

## When something goes wrong, live

| What happened | Say |
|---|---|
| The attacker reaches the DJI | "That one got through, and that is the honest state of it. Three defenders cannot seal a circle; they can only turn to meet the threat." |
| The ring goes cyan and stops | "The geofence tripped: the DJI left the box the ring can hold, so the ring parked instead of following it out." |
| A drone lands by itself | "It lost tracking, so it landed. That is the rule: no position, no flight." |
| A drone never arms | "A firmware safety latch. It needs a battery re-plug, which is deliberate." |
| Nothing happens at all | "Give me a moment, this is a research rig." Then stop talking and fix it. |

## Claims to keep honest

- **"It cannot get through"** is true for *this room and these settings*, not in general.
- Say the attacker is **as fast as** the defenders, never "faster". It plans at 0.8 m/s,
  but its commands go through the same 0.6 m/s limit.
- **"Ten different attacks"** is true: runs that differed only in the defenders' starting
  places produced attacks from all around the circle.
- "I don't know, I can find out" is a good answer. Never upgrade a claim under pressure.
