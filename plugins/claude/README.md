SimPeople lets your agent arrange animated people and activities in an Isaac Sim scene. Install the shared runtime and MCP dependency first, then start or attach to a live Isaac session. Use the included workflow to inspect capabilities, submit activities, monitor outcomes, change selected goals and settle cancellation. See [host setup](https://github.com/ros-claw/simpeople/blob/main/docs/plugins.md) for installation. The default endpoint is loopback port 8768. Each host package sets a distinct stable controller ID so reconnects retain the same logical owner. Configure distinct SIMPEOPLE_CONTROLLER_ID values for independent instances of the same host, and set SIMPEOPLE_ENDPOINT for custom sessions. Codex requires explicit env or env_vars forwarding; parent shell variables alone are insufficient. NVIDIA character and animation assets are supplied separately by your Isaac installation.

```text
/plugin install simpeople --marketplace ros-claw/simpeople
```
