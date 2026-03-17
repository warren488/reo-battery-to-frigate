#!/usr/bin/env bash
# Generates a short test video clip and uploads it via FTP,
# simulating what a Reolink camera would do.
#
# Usage: ./scripts/test-upload.sh [filename]
#   filename defaults to "test_clip_<timestamp>.mp4"

set -euo pipefail

FILENAME="${1:-test_clip_$(date +%s).mp4}"
TMPDIR="$(mktemp -d)"

echo "Generating a 5-second test clip..."

# Generate the clip into a temp directory
docker run --rm -v "${TMPDIR}:/out" --entrypoint ffmpeg linuxserver/ffmpeg \
  -hide_banner -loglevel warning \
  -f lavfi -i "color=c=yellow:s=2560x1440:r=20:d=5" \
  -f lavfi -i "sine=frequency=440:duration=5" \
  -vf "drawtext=text='TEST CLIP %{pts\:hms}':fontsize=80:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2" \
  -c:v libx264 -preset ultrafast \
  -c:a aac \
  -y "/out/${FILENAME}"

echo "Uploading ${FILENAME} via FTP..."

# Upload to the FTP server (same as a Reolink camera would)
FTP_USER="${FTP_USER:-reolink}"
FTP_PASS="${FTP_PASS:-reolink}"
FTP_HOST="${FTP_HOST:-localhost}"

curl -T "${TMPDIR}/${FILENAME}" "ftp://${FTP_USER}:${FTP_PASS}@${FTP_HOST}/${FILENAME}"

rm -rf "${TMPDIR}"

echo ""
echo "Done! Uploaded ${FILENAME} via FTP."
echo "The bridge should detect it and start streaming within a few seconds."
echo "Check logs with: docker compose logs -f reo-bridge"
