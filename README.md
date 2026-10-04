# anki-guard

Credits a day once Anki's own "studied today" figure reaches **20 minutes**,
every day. The credit is a signed row that [earned_time]'s `anki` earner turns
into 30 min of gaming time and a 30-min-later shutdown; without it, the base
day is 30/30 shorter.

```
AnkiDroid (phone) --sync--> anki --syncserver (PC, :8780, LAN)
                                   |  collection.anki2 (+ -wal)
                     anki-guard.timer (10 min): copy, query revlog
                                   |
                ~/.local/share/anki_guard/ledger.json  (HMAC credit rows)
                                   |
             screen-locker (shutdown)  steam-backlog-enforcer (gaming)
```

## Install

```console
./install.sh                    # package, sync account, units, health check
scripts/setup_phone.sh          # AnkiDroid -> http://<PC LAN IP>:8780/
scripts/setup_phone.sh --verify-only
python3 -m anki_guard status    # read-only one-liner
```

Desktop Anki can sync to the same server: Preferences -> Syncing -> custom
sync URL `http://<PC LAN IP>:8780/`, same account.

## The metric

`SELECT id, time FROM revlog WHERE id > <day start> AND type NOT IN (4, 5)`,
the day starting at the collection's rollover hour exactly as Anki computes
`next_day_at - 86400`. `time` is already capped per deck by "Maximum answer
seconds". The credit's `detail.anki_day` is what the earner matches on, and
`detail.studied_at` is when the running total crossed 20 minutes.

[earned_time]: https://github.com/kuhyx/utils/tree/main/earned_time
