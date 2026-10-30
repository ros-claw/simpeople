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
        server={'type':'stdio','command':'simpeople','args':['mcp']}
        if host=='codex':
            (root/'plugin.json').write_text(json.dumps({'$schema':'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json',**common},indent=2)+'\n')
            (root/'mcp.json').write_text(json.dumps({'$schema':'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json','mcpServers':{'simpeople':server}},indent=2)+'\n')
        else:
            (root/'.claude-plugin').mkdir(exist_ok=True)
            (root/'.claude-plugin/plugin.json').write_text(json.dumps(common,indent=2)+'\n')
            (root/'.mcp.json').write_text(json.dumps({'mcpServers':{'simpeople':server}},indent=2)+'\n')
        (root/'README.md').write_text('SimPeople lets your agent arrange animated people and activities in an Isaac Sim scene. Install the shared runtime and MCP dependency first, then start or attach to a live Isaac session. Use the included workflow to inspect capabilities, submit activities, monitor outcomes, change selected goals and settle cancellation. See ../../docs/plugins.md for installation. The default endpoint is loopback port 8768. For custom sessions, configure SIMPEOPLE_ENDPOINT and a distinct SIMPEOPLE_CONTROLLER_ID in the host MCP environment. Codex requires explicit env or env_vars forwarding; parent shell variables alone are insufficient. NVIDIA character and animation assets are supplied separately by your Isaac installation.\n')
if __name__=='__main__':build()
