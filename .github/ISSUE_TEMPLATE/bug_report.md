---
name: Bug report
about: Something isn't working
labels: bug
---

**What happened?**

<!-- What did you expect, and what did you see instead? -->

**Setup**

- Camera model / firmware:
- Stream settings (`STREAM_WIDTH`×`STREAM_HEIGHT`@`STREAM_FPS`):
- How you consume the stream (Frigate version / VLC / other):
- OS + Docker version:

**Logs**

<!-- Paste the relevant part of: docker compose logs reo-bridge
     Lines prefixed with "encoder:" are the output FFmpeg's own diagnostics. -->

```
(logs here)
```

**Web UI status card** (if reachable)

<!-- What does http://<host>:5001 show — idle/streaming/encoder down? Queue depth? -->
