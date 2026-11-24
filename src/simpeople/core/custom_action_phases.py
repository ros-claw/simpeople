"""Validate explicit per-source phases without importing Kit or touching USD."""
import hashlib
import math
from pathlib import Path

TAGS = ('ActionStart', 'ActionLoop', 'ActionEnd')


def source_plan(entry, resolve, inspect):
    """Return checked main/exit sources for a single named SDK action.

    Empty phases mean no annotation, rather than a zero-duration annotation.
    Each source can declare its own skeleton; SDK imports append variants to the
    same action before actors exist. This function grants no playback proof.
    """
    specs = entry.get('experimental_phase_sources')
    if entry.get('playback_mode') != 'loop' or not isinstance(specs, list) or not 2 <= len(specs) <= 32:
        raise ValueError('main source and bounded exit variants required')
    result = []; seen = set()
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict) or set(spec.get('phases', {})) != set(TAGS):
            raise ValueError('all three phases must be explicit')
        if index == 0 and any(spec.get(k) != entry.get(k) for k in ('clip', 'skeleton')):
            raise ValueError('first phase source must preserve the main clip and skeleton')
        resolved = {}
        for key in ('clip', 'skeleton'):
            uri = spec.get(key)
            if not isinstance(uri, str) or not uri.startswith('cache://'):
                raise ValueError('phase sources require local cache URIs')
            path = Path(resolve(uri)).resolve()
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != spec.get('source_sha256', {}).get(key):
                raise ValueError('phase source digest differs: '+key)
            resolved[key] = str(path)
        if resolved['clip'] in seen:
            raise ValueError('duplicate phase animation source')
        seen.add(resolved['clip'])
        metadata = inspect(resolved['skeleton'], resolved['clip'])
        frames = spec.get('frames')
        if (type(frames) is not int or frames < 2 or frames != metadata['frames']
                or metadata['first_frame'] != 0 or metadata['last_frame'] != frames-1
                or metadata['fps'] != 30 or not metadata['joint_layout_matches']):
            raise ValueError('phase sample range, rate or source skeleton differs')
        phases = {}
        for tag in TAGS:
            span = spec['phases'][tag]
            if span is None:
                phases[tag] = None
            elif (not isinstance(span, list) or len(span) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in span)
                    or not 0 <= span[0] <= span[1] <= frames-1):
                raise ValueError('phase range exceeds its own source: '+tag)
            else:
                phases[tag] = list(span)
        if index == 0:
            if phases['ActionStart'] is None or phases['ActionLoop'] != [0, frames-1] or phases['ActionEnd'] is not None:
                raise ValueError('main source must retain its full loop and omit its old exit')
        elif phases != {'ActionStart': None, 'ActionLoop': None, 'ActionEnd': [0, frames-1]}:
            raise ValueError('exit variants must belong exclusively to ActionEnd')
        result.append(dict(**resolved, phases=phases, frames=frames,
                           source_sha256=dict(spec['source_sha256'])))
    return result


def annotation_arguments(spec):
    return {field: [tuple(spec['phases'][tag]) if spec['phases'][tag] is not None else ()]
            for field, tag in zip(('action_start_ranges', 'action_loop_ranges', 'action_end_ranges'), TAGS)}
