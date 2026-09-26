# Docker files

| file | what |
|---|---|
| `Dockerfile.pi-toolchain` | `swe25-pi-toolchain:0.80.3`: node 24 + Pi 0.80.3 (amd64). Built by `swe25 build-toolchain`. |
| `Dockerfile.pi-overlay` | `swe25-pi:<instance>`: an instance image plus node + Pi. |
| `Dockerfile.claude` | `swe25-claude:<instance>`: an instance image plus Claude Code. |
| `pi_bash_0.80.3.js` | Pi's bash tool with per-command timeouts (below). |
| `pi_bash_0.80.3.orig.js` | The untouched Pi 0.80.3 file it was built from, kept for diffing. |

## The bash-tool timeout patch

Pi 0.80.3's bash tool (`core/tools/bash.js`) declares its `timeout` parameter as *"optional, no
default timeout"* and only arms a killer when the model passes one. A command the model runs
**without** a `timeout` can therefore hang until the whole agent cap: a stalled network test once
sat at 0% CPU for 22 minutes.

`pi_bash_0.80.3.js` replaces that timeout block to enforce, per command:

* **idle (no-output) timeout**: `PI_BASH_IDLE_TIMEOUT`, 600 s. Re-armed on every stdout/stderr
  chunk, so a live test that keeps printing is never cut off; only a true stall trips it.
* **wall backstop**: the model's own `timeout` if it set one, else `PI_BASH_WALL_TIMEOUT`,
  1800 s. A model that knows a test is legitimately long can raise it by passing a larger
  `timeout`.

Whichever limit trips first kills the process tree. The model sees the same
`Command timed out after N seconds` result it would for its own timeout.

The harness bind-mounts the patched file read-only over Pi's, but only after checking that the
image's stock `bash.js` has md5 `8e91e32c1bf077fa87f02d9c7c6cc58e`. On a mismatch the cell is
**aborted**, never run on an unpatched agent, because that would not be comparable with the
baselines.
