#!/bin/bash
# One line a minute of how hot this Pi runs, how fast, and on what power (20 Oct 2026).
#
# Why: one camera Pi runs far hotter than its twin, and its camera stalls now and then
# with no error. This is the record to test whether the stalls follow the heat, and to
# compare the two Pis like for like (a Pi short of power slows itself down, and so runs
# cooler: the comparison means nothing without the clock and the throttle flags).
#
# Run by systemd-files/picamera-thermal.timer as the streamer's own user, which can read
# the firmware (group video) and writes to the streamer's state directory. Independent
# of the streamer, so it keeps logging while the streamer is stalled or restarting.
#
# One CSV per month in $STATE_DIRECTORY (normally /var/lib/picamera), about 4 MB each;
# files over 13 months old are removed. Columns:
#   utc            time of the reading
#   soc_c          the SoC's temperature
#   sensor_c       the camera sensor's, if the streamer recorded it in the last 2 minutes
#   arm_mhz        CPU clock at that moment (600 when under-voltage or heat holds it back)
#   core_v         core voltage
#   throttled      vcgencmd get_throttled: bit 0 under-voltage now, 2 throttled now,
#                  16/17/18 the same "has happened since boot" (see the Pi docs)
#   load1          1-minute load average
#   streamer       systemctl is-active picamera
#   streamer_cpu   the streamer's CPU use since the previous line, in % of one core
set -u

DIR="${STATE_DIRECTORY:-/var/lib/picamera}"
now=$(date -u +%s)
file="$DIR/thermal-$(date -u +%Y-%m).csv"
[ -s "$file" ] || echo "utc,soc_c,sensor_c,arm_mhz,core_v,throttled,load1,streamer,streamer_cpu" > "$file"

soc=$(vcgencmd measure_temp 2>/dev/null | sed -E 's/temp=([0-9.]+).*/\1/')
arm_hz=$(vcgencmd measure_clock arm 2>/dev/null | cut -d= -f2)
arm=$(( ${arm_hz:-0} / 1000000 ))
volt=$(vcgencmd measure_volts core 2>/dev/null | sed -E 's/volt=([0-9.]+)V/\1/')
throttled=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)
load=$(cut -d' ' -f1 /proc/loadavg)

sensor=""
if [ -f "$DIR/sensor-temp" ] && [ $(( now - $(stat -c %Y "$DIR/sensor-temp") )) -lt 120 ]; then
  sensor=$(tr -d '\n' < "$DIR/sensor-temp")
fi

state=$(systemctl is-active picamera 2>/dev/null)
cpu=""
ns=$(systemctl show picamera -p CPUUsageNSec --value 2>/dev/null)
if [[ "$ns" =~ ^[0-9]+$ ]]; then
  if read -r last_t last_ns < "$DIR/.thermal-last" 2>/dev/null && [ "$ns" -ge "$last_ns" ] && [ "$now" -gt "$last_t" ]; then
    cpu=$(awk -v d="$(( ns - last_ns ))" -v s="$(( now - last_t ))" 'BEGIN { printf "%.1f", d / (s * 1e7) }')
  fi
  echo "$now $ns" > "$DIR/.thermal-last"
fi

echo "$(date -u -d "@$now" +%FT%TZ),$soc,$sensor,$arm,$volt,$throttled,$load,$state,$cpu" >> "$file"
find "$DIR" -maxdepth 1 -name 'thermal-*.csv' -mtime +400 -delete 2>/dev/null
exit 0
