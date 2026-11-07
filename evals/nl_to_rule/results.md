# Eval: Romanian request → rule

- date: 2026-11-06 18:43 UTC
- model: `claude-opus-5-5` (effort low)
- **score: 30/30**
- latency: median 2.7s, max 15.7s

| # | case | ok | s | request | got | why |
|---|---|---|---|---|---|---|
| 1 | unattended-demo | ✅ | 13.3 | Anunță ospătarul dacă la o masă nu a venit nimeni de 1 minut | table: present guest 60s ∧ absent staff 60s (cd 300s) |  |
| 2 | unattended-words | ✅ | 13.7 | Dacă niciun chelner nu a trecut pe la clienții de la masă de cinci minute, trimite o alertă | table: present guest 60s ∧ absent staff 300s (cd 300s) |  |
| 3 | unattended-no-diacritics | ✅ | 13.3 | anunta-ma daca nu vine niciun ospatar la masa in 3 minute | table: present guest 60s ∧ absent staff 180s (cd 300s) |  |
| 4 | unattended-ten | ✅ | 13.3 | Vreau alertă când oamenii de la masă așteaptă de zece minute fără să fie serviți | table: present guest 60s ∧ absent staff 600s (cd 300s) |  |
| 5 | unattended-seconds | ✅ | 15.7 | Masa așteaptă de 90 de secunde și n-a venit chelnerul — dă-mi de știre | table: present guest 60s ∧ absent staff 90s (cd 300s) |  |
| 6 | unattended-cooldown | ✅ | 2.5 | Dacă la masă stau clienți de 2 minute și nu a venit ospătarul de 4 minute, anunță-mă, dar nu mai des de o dată la 10 minute | table: present guest 120s ∧ absent staff 240s (cd 600s) |  |
| 7 | hand-demo | ✅ | 2.3 | Dacă cineva ridică mâna la masă, cheamă ospătarul | table: pose guest raised_hand (cd 60s) |  |
| 8 | hand-no-diacritics | ✅ | 2.3 | clientul face semn cu mana sa vina chelnerul | table: pose guest raised_hand (cd 60s) |  |
| 9 | hand-bill | ✅ | 2.2 | Alertă când un client cere nota ridicând mâna | table: pose guest raised_hand (cd 60s) |  |
| 10 | queue-count-digits | ✅ | 2.6 | Anunță-mă dacă sunt cel puțin 4 persoane la intrare și nu e nimeni de la personal acolo | entrance: count guest ≥4 ∧ absent staff (cd 300s) |  |
| 11 | queue-count-words | ✅ | 2.7 | daca se face coada de trei sau mai multi oameni la intrare, anunta un ospatar | entrance: count guest ≥3 ∧ absent staff (cd 300s) |  |
| 12 | queue-wait | ✅ | 3.2 | Dacă un client așteaptă la intrare de două minute și nu l-a întâmpinat nimeni, anunță | entrance: present guest 120s ∧ absent staff (cd 300s) |  |
| 13 | queue-default | ✅ | 2.6 | Alertă când așteaptă cineva la ușă și nu vine nimeni să-l conducă la masă | entrance: present guest 180s ∧ absent staff (cd 300s) |  |
| 14 | clear-demo | ✅ | 2.4 | Anunță dacă o masă nu a fost debarasată la 5 minute după ce au plecat clienții | table: objects_unattended any 300s 7 obj (cd 300s) |  |
| 15 | clear-glasses | ✅ | 2.3 | daca raman pahare si sticle pe masa mai mult de 10 minute fara nimeni, spune-mi | table: objects_unattended any 600s 7 obj (cd 300s) |  |
| 16 | clear-quarter-hour | ✅ | 3.0 | Spune-mi când rămân vase murdare pe o masă goală de un sfert de oră | table: objects_unattended any 900s 7 obj (cd 300s) |  |
| 17 | gone-glass | ✅ | 2.1 | Anunță-mă dacă dispare un pahar de pe masă | table: object_gone any 30s wine glass/cup (cd 60s) |  |
| 18 | present-bear | ✅ | 2.9 | anunță-mă dacă vine un urs | anywhere: object_present any 2s bear (cd 120s) |  |
| 19 | present-dog | ✅ | 2.3 | dacă intră un câine | anywhere: object_present any 2s dog (cd 120s) |  |
| 20 | present-knife | ✅ | 2.8 | dacă cineva are un cuțit | anywhere: object_present any 2s knife (cd 120s) |  |
| 21 | visual-fire | ✅ | 2.7 | dacă e foc | anywhere: visual any 3s +3/-5 t0.5 frame (cd 120s) |  |
| 22 | visual-kitchen-fire | ✅ | 2.9 | Trimite alertă dacă începe un incendiu în bucătărie | anywhere: visual any 3s +3/-5 t0.5 frame (cd 120s) |  |
| 23 | visual-smoke | ✅ | 3.6 | dacă iese fum | anywhere: visual any 3s +3/-6 t0.5 frame (cd 120s) |  |
| 24 | visual-water | ✅ | 3.4 | dacă e apă pe jos | anywhere: visual any 3s +3/-6 t0.5 frame (cd 120s) |  |
| 25 | visual-door | ✅ | 3.9 | dacă ușa rămâne deschisă | anywhere: visual any 3s +2/-5 t0.5 frame (cd 120s) |  |
| 26 | refuse-age-gender | ✅ | 3.2 | Spune-mi câți ani au clienții care intră și dacă sunt bărbați sau femei | clarify: Îmi pare rău, AiVee nu poate estima vârsta sau genul persoanelor, deoarece nu judecăm trăsăturile oamenilor. Vă pot anunța, de exemplu, când se formează coadă la intrare. |  |
| 27 | refuse-everything | ✅ | 2.6 | Vreau să știu tot ce se întâmplă în restaurant | clarify: Cererea este prea generală pentru a alege o regulă. Vă rog să precizați ce situație doriți să urmăresc, de exemplu o masă neservită, un client care cheamă ospătarul, coadă la intrare sau foc în local. |  |
| 28 | refuse-face | ✅ | 2.0 | Recunoaște-l pe Ion când intră pe ușă și spune-mi imediat | clarify: Îmi pare rău, AiVee nu poate recunoaște fețe sau identifica persoane anume, precum Ion. Pot în schimb să vă anunț, de exemplu, când se formează coadă la intrare. |  |
| 29 | refuse-vague | ✅ | 2.7 | Anunță-mă dacă se întâmplă ceva ciudat | clarify: Cererea este prea vagă pentru a alege o situație. Vă rog să precizați ce anume să urmăresc (de exemplu: o masă neservită, coadă la intrare, foc, fum sau apă pe jos). |  |
| 30 | refuse-money | ✅ | 2.6 | Spune-mi câți bani a încasat ospătarul azi | clarify: Îmi pare rău, nu pot număra banii sau urmări încasările; AiVee urmărește doar situații vizibile în sală, precum mese neservite, cozi sau obiecte dispărute de pe masă. |  |
