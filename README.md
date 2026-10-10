# anki-guard

> **Retired as a gate** from earned_time's `TUTOR_FROM`: the `anki` earner is
> gone and `automation` is paid per block by the Automation tutor. No quota is
> enforced and nothing is credited; `python3 -m anki_guard status` still
> reports study, and `anki-syncserver` keeps serving the decks. The rest of
> this file describes the gate as it ran until then.

Two daily quotas on one collection, each credited as a signed row that an
[earned_time] earner turns into gaming time and a later shutdown:

| quota | counts | bar | ledger |
|---|---|---|---|
| `anki` | every deck **except** `Automation` | 12 min on workdays, 20 min other days | `ledger.json` |
| `automation` | **only** `Automation` and its subdecks | 8 min on workdays, 25 min other days | `automation_ledger.json` |

Workdays are `freedays.WORKDAYS` (Tue-Thu), the definition leetcode-guard,
screen-locker and wake-alarm share; both workday bars together take 20 min.

The decks are disjoint, so one review never pays both. A card in a filtered
deck counts for its home deck; a review of a since-deleted card counts for
`anki`. The `automation` deck is the PLC / industrial-control security study track.

```
AnkiDroid --https--> Caddy (anki.kuhy.duckdns.org) --> anki --syncserver (127.0.0.1:8780)
                                   |  collection.anki2 (+ -wal)
                     anki-guard.timer (10 min): copy, query revlog
                                   |
   ~/.local/share/anki_guard/{ledger,automation_ledger}.json  (HMAC credit rows)
                                   |
             screen-locker (shutdown)  steam-backlog-enforcer (gaming)
```

## Install

```console
./install.sh                    # package, sync account, units, Caddy site, health checks
scripts/setup_phone.sh          # AnkiDroid -> https://anki.kuhy.duckdns.org/
scripts/setup_phone.sh --verify-only
python3 -m anki_guard status    # read-only one-liner
```

Desktop Anki can sync to the same server: Preferences -> Syncing -> custom
sync URL `https://anki.kuhy.duckdns.org/`, same account.

The server only listens on 127.0.0.1; the host Caddy edge (`gitea-caddy`)
terminates TLS, so the phone syncs from any network and no firewall port is
opened. `install.sh` owns `~/services/gitea/sites/anki.caddy`.

## The metric

`revlog` rows with `id > <day start> AND type NOT IN (4, 5)`, joined to the
card's home deck (`odid` if set, else `did`), the day starting at the collection's rollover hour exactly as Anki computes
`next_day_at - 86400`. `time` is already capped per deck by "Maximum answer
seconds". The credit's `detail.anki_day` is what the earner matches on, and
`detail.studied_at` is when the running total crossed the quota's bar.

[earned_time]: https://github.com/kuhyx/utils/tree/main/earned_time
