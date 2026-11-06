# Eval: Romanian request → rule

- date: 2026-11-06 09:43 UTC
- model: `claude-opus-5-5` (effort low)
- **score: 20/20**
- latency: median 2.4s, max 4.0s

| # | case | ok | s | request | got | why |
|---|---|---|---|---|---|---|
| 1 | unattended-demo | ✅ | 2.2 | Anunță ospătarul dacă la o masă nu a venit nimeni de 1 minut | table: present guest 60s ∧ absent staff 60s (cd 300s) |  |
| 2 | unattended-words | ✅ | 2.5 | Dacă niciun chelner nu a trecut pe la clienții de la masă de cinci minute, trimite o alertă | table: present guest 60s ∧ absent staff 300s (cd 300s) |  |
| 3 | unattended-no-diacritics | ✅ | 4.0 | anunta-ma daca nu vine niciun ospatar la masa in 3 minute | table: present guest 60s ∧ absent staff 180s (cd 300s) |  |
| 4 | unattended-ten | ✅ | 2.8 | Vreau alertă când oamenii de la masă așteaptă de zece minute fără să fie serviți | table: present guest 60s ∧ absent staff 600s (cd 300s) |  |
| 5 | unattended-seconds | ✅ | 2.9 | Masa așteaptă de 90 de secunde și n-a venit chelnerul — dă-mi de știre | table: present guest 60s ∧ absent staff 90s (cd 300s) |  |
| 6 | unattended-cooldown | ✅ | 2.7 | Dacă la masă stau clienți de 2 minute și nu a venit ospătarul de 4 minute, anunță-mă, dar nu mai des de o dată la 10 minute | table: present guest 120s ∧ absent staff 240s (cd 600s) |  |
| 7 | hand-demo | ✅ | 3.6 | Dacă cineva ridică mâna la masă, cheamă ospătarul | table: pose guest raised_hand (cd 60s) |  |
| 8 | hand-no-diacritics | ✅ | 2.6 | clientul face semn cu mana sa vina chelnerul | table: pose guest raised_hand (cd 60s) |  |
| 9 | hand-bill | ✅ | 2.2 | Alertă când un client cere nota ridicând mâna | table: pose guest raised_hand (cd 60s) |  |
| 10 | queue-count-digits | ✅ | 2.2 | Anunță-mă dacă sunt cel puțin 4 persoane la intrare și nu e nimeni de la personal acolo | entrance: count guest ≥4 ∧ absent staff (cd 300s) |  |
| 11 | queue-count-words | ✅ | 2.8 | daca se face coada de trei sau mai multi oameni la intrare, anunta un ospatar | entrance: count guest ≥3 ∧ absent staff (cd 300s) |  |
| 12 | queue-wait | ✅ | 2.3 | Dacă un client așteaptă la intrare de două minute și nu l-a întâmpinat nimeni, anunță | entrance: present guest 120s ∧ absent staff (cd 300s) |  |
| 13 | queue-default | ✅ | 3.1 | Alertă când așteaptă cineva la ușă și nu vine nimeni să-l conducă la masă | entrance: present guest 180s ∧ absent staff (cd 300s) |  |
| 14 | clear-demo | ✅ | 2.2 | Anunță dacă o masă nu a fost debarasată la 5 minute după ce au plecat clienții | table: objects_unattended any 300s 7 obj (cd 300s) |  |
| 15 | clear-glasses | ✅ | 2.0 | daca raman pahare si sticle pe masa mai mult de 10 minute fara nimeni, spune-mi | table: objects_unattended any 600s 7 obj (cd 300s) |  |
| 16 | clear-quarter-hour | ✅ | 2.4 | Spune-mi când rămân vase murdare pe o masă goală de un sfert de oră | table: objects_unattended any 900s 7 obj (cd 300s) |  |
| 17 | refuse-face | ✅ | 2.1 | Recunoaște-l pe Ion când intră pe ușă și spune-mi imediat | clarify: Îmi pare rău, AiVee nu recunoaște fețe și nu identifică persoane anume, cum ar fi Ion. Vă pot anunța în schimb când se formează o coadă la intrare sau când așteaptă clienți acolo fără să fie preluați. |  |
| 18 | refuse-vague | ✅ | 1.6 | Anunță-mă dacă se întâmplă ceva ciudat | clarify: Vă rog să precizați ce situație doriți să urmăresc: masă neservită, client care cheamă ospătarul, coadă la intrare sau masă nedebarasată. |  |
| 19 | refuse-fire | ✅ | 2.0 | Trimite alertă dacă începe un incendiu în bucătărie | clarify: Îmi pare rău, AiVee nu poate detecta incendii; monitorizează doar servirea clienților (mese neservite, clienți care cheamă ospătarul, coadă la intrare, mese nedebarasate). Pentru incendii vă recomandăm un sistem dedicat de detecție a fumului. |  |
| 20 | refuse-money | ✅ | 2.1 | Spune-mi câți bani a încasat ospătarul azi | clarify: Îmi pare rău, AiVee nu poate număra bani sau calcula încasările ospătarilor. Vă pot ajuta în schimb cu alerte pentru mese neservite, clienți care cheamă ospătarul, coadă la intrare sau mese nedebarasate. |  |
