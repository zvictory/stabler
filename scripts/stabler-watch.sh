#!/bin/sh
# stabler-watch — are the tenants' background jobs actually being processed?
#
# Exists because of the 2026-07-28 outage: supervisor respawned the three bench
# worker programs 85 297 times over 43.7 h and nothing said so. The only symptom
# was a log file growing. Post-mortem: stabler repo,
# .claude/skills/stabler-deploy/SKILL.md, "Prod-only supervisor edit".
#
# Two deliberate refusals, both learned from that outage:
#
#   1. It never uses bench, the venv, or a Frappe background job. When the
#      workers are dead, anything that runs *as* a background job is dead too,
#      so a Frappe-side alert would have stayed silent for the same 43.7 h.
#      It reads supervisor and redis directly.
#
#   2. It never restarts anything. Unbounded automatic restart is precisely
#      what produced the 85 297 respawns. This reports; a human decides.

set -u

ENV_FILE=/root/.stabler-watch.env
STATE_FILE=/var/lib/stabler-watch/state
DELIVERED_SECONDS=21600  # 6 h — the alert landed; nag at this interval
UNDELIVERED_SECONDS=1800 # 30 min — it did not land; retry sooner, but do not
                         # spam the journal every tick, which is the same
                         # failure mode this whole watchdog exists to stop

mkdir -p "$(dirname "$STATE_FILE")"

# ------------------------------------------------------------------ checks
problems=""
add() { problems="$problems${problems:+; }$1"; }

sv=$(supervisorctl status 2>&1)
# Not `$?`: supervisorctl exits non-zero merely because a program is stopped.
# The real question is whether it answered with program lines at all.
if [ "$(printf '%s\n' "$sv" | awk '$1 ~ /^frappe-bench/' | wc -l)" -eq 0 ]; then
	add "supervisord unreachable — $(printf '%s\n' "$sv" | head -1)"
else
	# STARTING is not a fault: startsecs=20 means a healthy boot sits there
	# for 20 s, and this timer must not alert on an ordinary bench restart.
	bad=$(printf '%s\n' "$sv" | awk '$1 ~ /^frappe-bench/ && $2 != "RUNNING" && $2 != "STARTING" {printf "%s=%s ", $1, $2}')
	[ -n "$bad" ] && add "supervisor: $bad"
fi

for probe in queue:11000 cache:13000; do
	port=${probe#*:}
	[ "$(redis-cli -p "$port" ping 2>/dev/null)" = "PONG" ] ||
		add "redis-${probe%%:*} ($port) not answering"
done

# ------------------------------------------------------------ notify policy
[ -n "$problems" ] && status=PROBLEM || status=OK
digest=$(printf '%s' "$problems" | cksum | cut -d' ' -f1)

prev_status=OK prev_digest=0 prev_tried=0 prev_delivered=no
[ -f "$STATE_FILE" ] &&
	IFS='|' read -r prev_status prev_digest prev_tried prev_delivered < "$STATE_FILE"

now=$(date +%s)
notify=no
if [ "$status" = PROBLEM ]; then
	[ "$prev_delivered" = yes ] &&
		wait_for=$DELIVERED_SECONDS || wait_for=$UNDELIVERED_SECONDS
	if [ "$prev_status" != PROBLEM ] || [ "$digest" != "$prev_digest" ]; then
		notify=new
	elif [ $((now - prev_tried)) -ge "$wait_for" ]; then
		notify=still
	fi
elif [ "$prev_status" = PROBLEM ]; then
	notify=recovered
fi

# ------------------------------------------------------------------- report
if [ "$notify" != no ]; then
	host=$(hostname -s)
	case $notify in
	new)       text="🔴 stabler/$host — background jobs are not running.

$problems

No action was taken automatically. Check: sudo supervisorctl status" ;;
	still)     text="🔴 stabler/$host — still broken.

$problems" ;;
	recovered) text="🟢 stabler/$host — background jobs are running again." ;;
	esac

	sent=no
	if [ -r "$ENV_FILE" ]; then
		. "$ENV_FILE"
		if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
			# Token goes in via -K so it never appears in argv, which every
			# other user on this box can read out of `ps`.
			code=$(printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' \
					"$TELEGRAM_BOT_TOKEN" |
				curl -s -o /dev/null -w '%{http_code}' --max-time 15 -K - \
					--data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
					--data-urlencode "text=$text")
			[ "$code" = 200 ] && sent=yes || echo "telegram sendMessage failed: HTTP $code"
		else
			echo "$ENV_FILE sets no TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID — alert not delivered"
		fi
	else
		echo "$ENV_FILE missing — alert not delivered"
	fi
	# The journal keeps the alert whether or not Telegram took it, so a broken
	# notification channel cannot turn into a second silent outage.
	echo "[$notify sent=$sent] $problems"
	prev_tried=$now prev_delivered=$sent
fi

printf '%s|%s|%s|%s\n' "$status" "$digest" "$prev_tried" "$prev_delivered" > "$STATE_FILE"
