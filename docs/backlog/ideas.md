# AiVee — ideas, edge cases, open questions

A parking lot. Nothing here is scheduled. An item moves to the implementation plan
only when we explicitly decide "we build this now".

Status: `open` (just noted) · `clarified` (we agree what it means) · `approved` (go) · `dropped`

## Ideas

| # | Idea | Why | Status | Notes |
|---|------|-----|--------|-------|
| I1 | **Alert lifecycle after the alarm.** Today an alert is only `opened` / `closed`. Add the steps in between: `opened` (guest waits past the threshold) → `acknowledged` (a waiter stops the alarm on the phone) → `arrived` (the edge sees staff at that table) → `closed`. Stopping the alarm does not resolve the case; only the arrival at the table does. | Each step gets a timestamp, so we can measure what happens after the alarm. | open | Needs a `packages/contracts` change (`AlertEvent` has only `opened`/`closed`), so it needs its own task. Questions Q1–Q6. |
| I2 | **Service statistics built on I1.** (a) Total guest wait = from the guest sitting down to staff arriving. (b) Reaction time = from the alarm to the acknowledgement. (c) Travel time = from the acknowledgement to the arrival at the table. (d) Staffing pressure = alerts open at the same time and the average wait per hour of the day. Shown per shift, per day, per zone and per hour. | Answers "how long do guests wait?", "do I have enough waiters?" and "after seeing the alarm, how fast did the waiter really get there?". | open | Depends on I1. For (d), see Q6. |
| I3 | **Alert severity decides the channel.** Each rule has a severity. Proposal: `info` → a dashboard entry only; `normal` → a message (push or Telegram); `urgent` → a phone call. | A message is enough for minor issues; important ones must actually reach someone. | open | Today a rule has a single `action` of type `telegram`, `push` or `webhook` (`packages/contracts/.../rules.py`). There is no severity and no call channel, so this needs a contract change. Questions Q7–Q11. |

## Edge cases

| # | Situation | What should happen | Status | Notes |
|---|-----------|--------------------|--------|-------|
| E1 | A waiter acknowledges the alarm, but nobody reaches the table. | Proposal: after X minutes, alert again or escalate to the manager. | open | See Q2. |
| E2 | A waiter reaches the table without acknowledging. | Proposal: the alert still closes; we record "no acknowledgement" (this counts as reaction-time data too). | open | |
| E3 | A waiter only walks past the table. | It must not count as an arrival. Proposal: staff must stay in the table zone for at least N seconds. | open | See Q4. |
| E4 | Two waiters acknowledge the same alert. | Proposal: the first acknowledgement owns it; the alarm stops for everyone. | open | See Q5. |
| E5 | Nobody answers an urgent call (busy, phone on silent). | Proposal: call the next person on the list, or call again after N minutes. | open | See Q9. |
| E6 | The restaurant is busy and many urgent alerts open at once. | One call per alert would mean constant calls. Proposal: one call that summarises them, plus a limit on calls per minute. | open | |
| E7 | No internet, or the call provider is down. | The edge works offline, but a phone call needs the internet. Proposal: fall back to a push or a local alarm. | open | |

## Open questions

| # | Question | Who decides | Status | Answer |
|---|----------|-------------|--------|--------|
| Q1 | Who acknowledges the alarm: a named waiter (each with a login on their phone) or any staff phone, anonymously? Statistics per waiter need a name. The camera recognises "staff" only, never which person. | product | open | |
| Q2 | After an acknowledgement with no arrival, how long until we alert again, and to whom? | product | open | |
| Q3 | Does "arrived" also require the waiter to be the one who acknowledged? The camera cannot tell waiters apart, so for now: any staff member at the table resolves the alert. | product | open | |
| Q4 | Minimum time in the table zone for staff to count as arrived (for example 5–10 s)? | product + edge | open | |
| Q5 | Does an acknowledgement stop the alarm on all phones or only on the phone that acknowledged? | product | open | |
| Q6 | "Do I have enough waiters?" needs the number of waiters on shift. Does the manager enter it, or do we count the staff tracks the edge sees? | product | open | |
| Q7 | Which situations are urgent? For example: a guest waiting over 10 minutes, a raised hand ignored, an unattended object. Or does the owner choose the severity for each rule? | product | open | |
| Q8 | Does severity escalate over time? For example: a message at 5 minutes, a call at 10 minutes if still unresolved. Combined with I1, a call would happen only if nobody acknowledged. | product | open | |
| Q9 | Who gets called: the waiter on shift, the manager, a list in order? | product | open | |
| Q10 | Who places the call: a voice-call provider (Twilio or similar, costs money, needs internet) or Telegram/WhatsApp calls? Does the call play a recorded Romanian message? | tech | open | |
| Q11 | Do quiet hours apply (no calls outside the schedule)? Or does a call happen whenever an urgent alert fires? | product | open | |
