"""Resolve portable registry URIs without importing Kit."""
import os
from pathlib import Path

def resolve_asset_path(value,root):
    root=Path(root)
    for prefix,base in [('characters://',Path(os.environ.get('SIMPEOPLE_CHARACTER_DIR',root/'assets/characters'))),
                        ('animation://',Path(os.environ.get('SIMPEOPLE_ANIMATION_DIR',root/'assets/animations'))),('cache://',root/'assets/cache')]:
        if value.startswith(prefix):
            relative=Path(value[len(prefix):])
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('asset URI must stay inside its configured root')
            return str(base/relative)
    marker='/assets/cache/behavior/'
    if marker in value:return str(root/'assets/cache/behavior'/value.split(marker,1)[1])
    if '/Isaac/People/Characters/' in value and os.environ.get('SIMPEOPLE_CHARACTER_DIR'):
        return str(Path(os.environ['SIMPEOPLE_CHARACTER_DIR'])/value.split('/Isaac/People/Characters/',1)[1])
    return str(Path(os.path.expandvars(value)).expanduser())
