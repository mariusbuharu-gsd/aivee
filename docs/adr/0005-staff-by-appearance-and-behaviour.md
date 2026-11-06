# 5. Staff by appearance and behaviour, no face recognition

Date: 2026-11-06 · Status: accepted · Decision log: D3, D4

## Context

Every rule depends on telling staff from guests ("nobody from staff came to the table").
Face recognition would identify people, which is biometric data under GDPR art. 9, is
regulated by the EU AI Act and is not what an owner needs: the role matters, not the name.

## Decision

AiVee recognises the **role**, never the person. Per track, it fuses two signals:

- **appearance**: CLIP embedding of the person crop compared with staff examples
  (2–3 uniform photos or a short video, plus a text description such as "burgundy T-shirt");
- **behaviour**: distance per minute, tables visited, share of time stationary, time in staff zones.

`staff_score = 0.5 · behaviour + 0.5 · appearance`, with hysteresis (staff above 0.7, guest
below 0.4). When a track looks like staff, the edge sends a suggestion; the owner confirms
or rejects it with one tap, and confirmed crops become new examples.

Faces are blurred on the device before any snapshot leaves it. Face recognition is out of scope.

## Consequences

- No training per restaurant: a few photos and a sentence are enough.
- Works with faces blurred or turned away.
- Two waiters cannot be told apart; statistics are per role, not per person.
- A guest dressed like staff can be misread; owner confirmation and behaviour reduce this.
