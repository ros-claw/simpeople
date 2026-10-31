"""Generate two thin host packages from one canonical workflow and MCP entry."""
import json
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1]
def build():
    for host in ('codex','claude'):
        root=ROOT/'plugins'/host
        (root/'skills/simpeople').mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/'skills/simpeople/SKILL.md',root/'skills/simpeople/SKILL.md')
        if (ROOT/'LICENSE').exists():shutil.copy2(ROOT/'LICENSE',root/'LICENSE')
        common={'name':'simpeople','version':'0.2.0','description':'Agent control of animated people and activities in Isaac Sim.',
                'author':{'name':'ROSClaw'},'repository':'https://github.com/ros-claw/simpeople','license':'MIT'}
        server={'type':'stdio','command':'simpeople','args':['mcp'],
                'env':{'SIMPEOPLE_CONTROLLER_ID':f'simpeople-{host}'}}
        if host=='codex':
            (root/'plugin.json').write_text(json.dumps({'$schema':'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json',**common},indent=2)+'\n')
            (root/'mcp.json').write_text(json.dumps({'$schema':'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json','mcpServers':{'simpeople':server}},indent=2)+'\n')
        else:
            (root/'.claude-plugin').mkdir(exist_ok=True)
            (root/'.claude-plugin/plugin.json').write_text(json.dumps(common,indent=2)+'\n')
            (root/'.mcp.json').write_text(json.dumps({'mcpServers':{'simpeople':server}},indent=2)+'\n')
        install=('codex plugin marketplace add ros-claw/simpeople\ncodex plugin add simpeople@ros-claw-simpeople' if host=='codex' else '/plugin install simpeople --marketplace ros-claw/simpeople')
        (root/'README.md').write_text('SimPeople lets your agent arrange animated people and activities in an Isaac Sim scene. Install the shared runtime and MCP dependency first, then start or attach to a live Isaac session. Use the included workflow to inspect capabilities, submit activities, monitor outcomes, change selected goals and settle cancellation. See [host setup](https://github.com/ros-claw/simpeople/blob/main/docs/plugins.md) for installation. The default endpoint is loopback port 8768. Each host package sets a distinct stable controller ID so reconnects retain the same logical owner. Configure distinct SIMPEOPLE_CONTROLLER_ID values for independent instances of the same host, and set SIMPEOPLE_ENDPOINT for custom sessions. Codex requires explicit env or env_vars forwarding; parent shell variables alone are insufficient. NVIDIA character and animation assets are supplied separately by your Isaac installation.\n\n```text\n'+install+'\n```\n')
if __name__=='__main__':build()
