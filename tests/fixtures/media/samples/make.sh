#!/usr/bin/env sh
# Rebuilds the real audio samples the sniff tests measure (issue-38 critic 3). Each is
# 1.5 s of a 440 Hz tone, encoded as a browser or a phone would write it. The tests hold
# the duration ffprobe reports for each; rerun this only if you change a sample.
set -eu
cd "$(dirname "$0")"
tone() { echo "sine=frequency=440:sample_rate=$1:duration=1.5"; }
run() { rate=$1; shift; ffmpeg -v error -y -f lavfi -i "$(tone "$rate")" -ac 1 -fflags +bitexact -map_metadata -1 "$@"; }
run 48000 -c:a aac -b:a 24k aac.m4a
run 48000 -c:a aac -b:a 24k -movflags +frag_keyframe+empty_moov+default_base_moof \
  -frag_duration 300000 aac-fragmented.m4a
run 44100 -c:a libmp3lame -b:a 32k mp3.mp3
run 8000 -c:a pcm_s16le pcm.wav
run 48000 -c:a libopus -b:a 12k opus.ogg
run 48000 -c:a libopus -b:a 12k opus.webm
run 48000 -c:a libopus -b:a 12k -live 1 -cluster_time_limit 500 opus-live.webm
run 48000 -c:a libvorbis -q:a 0 vorbis.ogg
run 48000 -c:a libopus -b:a 12k opus.mp4
for f in *.m4a *.mp3 *.wav *.ogg *.webm *.mp4; do
  printf '%s %s\n' "$f" "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")"
done
