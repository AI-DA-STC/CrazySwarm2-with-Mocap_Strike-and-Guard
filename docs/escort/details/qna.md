# Escort: questions and answers, by audience

What to say when someone asks something the [presenting script](../presenting.md) does not
cover. Each entry has a **short answer** you can say standing up, and sometimes a *push*
line for when they want more. Say the short one and stop: answering a one-line question for
ninety seconds is the fastest way to lose a technical room.

Two rules matter more than any answer here:

1. **"I don't know, I can find out" is a winning answer.** This is a research rig. Guessing
   in front of an engineer who knows the field is the one way to lose credibility.
2. **Never upgrade a claim under pressure.** Everything below is scoped to *this room,
   these four aircraft, these numbers*. "It cannot get through" is true here, not in
   general. If pushed to generalise: "that is the next question, not a result we have."

Numbers to read off: [reference.md, "Numbers"](reference.md#numbers). Prose copies of them
have drifted before.

---

## If you only get one question

> **"So what am I looking at?"**

Three small drones hold a defensive ring around a larger aircraft that a person flies by
hand. A fourth drone attacks. The ring rotates on its own so that whichever defender is
nearest the threat ends up between the threat and the thing it protects, and it keeps doing
that as the person moves the aircraft. Neither the attack nor the response is scripted;
only the attacker's opening move is.

---

## Tier 1: what almost everyone asks

**"Is this pre-programmed?"**
No. The defenders work out where the threat is twenty times a second; move the protected
aircraft and the whole ring follows and re-aims. The operator starts each of the
attacker's stages, but it finds its own way in, and it can give up on its own.
*Push:* four runs that differed only in where the defenders started produced 355° of
spread in the attacker's path.

**"Who is flying what?"**
The big one is hand-flown by a person, deliberately. The four small ones are autonomous.

**"What happens if they crash into each other?"**
Minimum distances are enforced in software on every command before it is sent. There is
also a geofence, automatic landing if the cameras lose an aircraft, and a one-click
emergency stop.
*Push:* 0.8 m between defenders, 1.0 m to the protected aircraft. The attacker keeps
itself 0.8 m from every defender; a defender only gives way inside 0.7 m.

**"How does it know where everything is?"**
Motion capture: cameras round the room track reflective markers at 50 Hz. All decisions
happen on this laptop and go out over one radio.

**"How fast are they going?"**
Everything is capped at 0.6 m/s, the attacker included: slower than walking pace.

**"Why is that one a different colour?"**
Colours are status, not decoration: red is the attacker, white the defender blocking right
now. ([Full legend](../how-it-works.md#what-the-lights-mean).)

**"How long did this take?"**
Be honest and specific. It lands better than a round number, and supervisors care.

---

## Tier 2: engineers and technical peers

**"What's the control loop?"**
Positions in at 50 Hz, full-state setpoints out at 20 Hz per aircraft over one radio. Each
drone runs its own estimator and attitude loop onboard; we command position, not attitude.

**"Is the attacker a planner or a potential field?"**
A potential field: attraction to the target, repulsion from each defender, a gap-seeking
term toward the widest opening, and a give-up timer. Deliberately not a planner: it should
look improvised and be beatable in a way we can reason about.

**"How does the ring decide who blocks?"**
It rotates the whole formation so a defender lands on the bearing to the threat. Slots are
ordered by bearing once, at the start, so drones never swap places. The blocker is whichever
slot is already nearest the threat, so the ring never turns more than 60°.

**"Three defenders can't cover a circle."**
Correct: the gaps are 1.73 m, which a drone fits through easily. The ring does not cover
the circle; it *rotates to meet the threat*. We tried spreading them out to cover more, and
the attacker got closer, not further away.

**"So could it get through?"**
Yes, if it is fast enough, or if the protected aircraft moves during the attack. The race
is angular: the defenders are on the inside track, so at the same speed they turn faster.
Break-even here is about 0.99 m/s of attacker speed; it flies at 0.6 at most. That is a
calculation we have partly validated, not a measured wall.

**"What's your latency?"**
Radio round-trip measured at 28–87 ms per aircraft. This is a slow position task, nowhere
near that limit.

**"What happens if you lose tracking on one?"**
After 0.3 s without a position it holds its point; after 1.0 s the show lands
everything. If the *protected* aircraft goes dark, the ring holds where it is rather than chase a
guess, and lands after 2 s. Without mocap the drones' estimators drift, so holding and
landing is the only safe response.

**"Why one radio? Isn't that a bottleneck?"**
It is, and it is the most interesting engineering problem in the rig. Four aircraft plus a
50 Hz broadcast share one 2.4 GHz link, so airtime is scarce. We have seen telemetry
failures where a drone went a second without hearing from us and its firmware dropped its
own logging; there is now an automatic recovery.

**"Simulation first, or straight to hardware?"**
Simulation first, always, and a planner re-verifies the geometry against the measured room
before anything arms. It refuses plans that do not fit, and has refused, correctly, more
than once.

---

## Tier 3: defence / counter-UAS visitors

They probe the gap between demo and capability. Lead with the limit, then the value.

**"Would this work outdoors?"**
Not as it stands: it depends on motion capture. Onboard sensing is a different, much harder
project. What transfers is the behaviour layer: slot assignment, rotate-to-threat, the
separation guarantees.

**"GPS-denied? Jamming?"**
Out of scope. Everything here assumes perfect positions and a clean link. We have partial
answers on what degrades first, because we have broken the radio link by accident.

**"Does it scale past three defenders?"**
The escort flies three. The guard demo in the same rig flies four defenders against three
attackers ([guard](../../guard/how-it-works.md)).

**"Would a net / jammer / shotgun not be simpler?"**
Usually yes, and that is fair. What is shown is not a better interceptor but coordinated
autonomous positioning against a target that moves unpredictably, which is the part that
generalises.

**"Do the defenders physically stop it?"**
No: they hold their line and the attacker gives way. Avoidance is assigned to the attacker
(0.8 m), which lets the defenders hold position; a defender gives way only inside 0.7 m.
Nobody rams anybody.

**"What's the detection range?"**
There is no detection: mocap gives the position. Engagement starts at 2.10 m, a software
threshold, not a sensor horizon.

---

## Tier 4: skeptical and awkward

**"This is just a toy demo though, isn't it?"**
The aircraft are toys, more or less; the coordination problem is not. Cheap airframes let
us run the experiment a hundred times without writing anything off.

**"What if I walk into the middle of it?"**
Please don't. There is a tested one-click emergency stop that cuts every motor. Standing
behind the line is the real answer.

**"What happens if you switch the cameras off?"**
Everything lands. Designed, not lucky: no position, no flight.

**"Can I fly the attacker?"**
There is a mode for exactly that: a person drives the attacker with a keyboard and the
defence reacts live. Not today: it has not had enough hours to put in front of guests.

**"Did you write all this or is it off the shelf?"**
Be specific and generous: the flight stack underneath is open source (Crazyswarm2 /
Crazyflie); the behaviour, safety layer and choreography are ours.

**"It looked like it got through."**
If it did, say so at once ([presenting.md](../presenting.md#when-something-goes-wrong-live)).

---

## Supervisors and management

**"Is it ready to show externally?"**
A scoped yes: as a demonstration with a trained operator in a prepared room. Not a product,
not unattended.

**"What's the risk of it going wrong in front of a visitor?"**
Non-zero, and "wrong" looks like a drone landing itself or the ring parking to wait. Both
are the safety layer working, both take one sentence to explain, neither is a crash. The
failure seen most is the *protected aircraft* flown out of its box.

**"What's next?"**
Stress test and rehearse. Then the human-driven attacker, which makes it a demonstration of
autonomy rather than a loop.

**"What would you need to go further?"**
The real blocker, not a wish list: the protected aircraft cannot move while it is under
attack, because turning the ring uses almost all of the defenders' speed. Fixing that costs
a lazier block or flying faster near people, which is a safety decision.

---

## Hard limits: the honest list

Every one of these will eventually be asked; each is better given freely than extracted.

* **Indoor only**, and **no sensing**: positions are given by motion capture, not perceived.
* **Three defenders do not seal a ring.** 1.73 m gaps; it rotates instead.
* **The attacker yields, not the defenders**, on purpose.
* **The attacker can win if it is fast enough:** ~0.99 m/s break-even; it flies at 0.6 at
  most. Say it is **as fast as** the defenders, never "faster": it plans at 0.8 m/s, but
  its commands go through the same 0.6 m/s limit.
* **The protected aircraft must hover during an attack.** While blocking, only 0.05 m/s of
  speed is left for following it.
* **The protected aircraft has a box**: it must stay a ring radius (1.0 m) inside the
  arena's edge, and it is the most likely thing to interrupt a run.
* **Four aircraft, one radio.**
* **This tuning is new.** The engagement distance was measured in simulation and has had
  little hardware time.
