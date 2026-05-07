# Media Fixtures

P0.1 FFmpeg probe tests generate the minimal WAV fixture at test time with
Python's standard library (`wave` and `struct`). This keeps the repository free
of binary media while still exercising a real, probeable container when
`ffprobe` is available.

If `ffprobe` is not installed in the execution environment, the positive probe
test skips and the missing-binary test still verifies the stable
`adapter.unavailable` response.
