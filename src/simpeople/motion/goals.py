"""Offline standing goals, retaining the observed support and body proportions."""
from .rig import validate_poses, world_to_local, forward_kinematics


def standing_upper_body_goal(source_world, measured_world, parents, tags, chain):
    """Transfer a measured limb configuration, never its unrelated stance.

    The returned pose is an authored goal, not an executed observation or live
    skeleton write. Source local translations and root/support are preserved.
    """
    import numpy as np
    source = validate_poses(source_world, len(parents))
    measured = validate_poses(measured_world, len(parents))
    if len(source) != 1 or len(measured) != 1:
        raise ValueError('single source and target poses required')
    if chain not in {'left_arm', 'right_arm', 'head', 'idle'}:
        raise ValueError('unsupported standing goal chain')
    local = world_to_local(source, parents)
    target = world_to_local(measured, parents)
    copied = []
    if chain != 'idle':
        tag = {'left_arm': 'LeftShoulder', 'right_arm': 'RightShoulder', 'head': 'Neck1'}[chain]
        if tag not in tags and chain == 'head':
            tag = 'Head'
        if tag not in tags:
            raise ValueError('standing goal lacks required semantic joint: ' + tag)
        root = tags[tag]
        if isinstance(root, bool) or not isinstance(root, int) or not 0 < root < len(parents):
            raise ValueError('invalid standing goal root')
        for joint in range(len(parents)):
            ancestor = joint
            while ancestor > root:
                ancestor = parents[ancestor]
            if ancestor == root:
                copied.append(joint)
        forbidden = {tags[t] for t in ['LeftLeg', 'LeftShin', 'LeftFoot', 'RightLeg', 'RightShin', 'RightFoot'] if t in tags}
        if forbidden.intersection(copied):
            raise ValueError('upper-body tags would modify a supporting leg')
        local[:, copied, 3:] = target[:, copied, 3:]
    world = forward_kinematics(local, parents)
    source_local = world_to_local(source, parents)
    if not np.allclose(local[:, :, :3], source_local[:, :, :3], atol=1e-10, rtol=0):
        raise ValueError('authored standing goal changed bone translations')
    supports = [tags[t] for t in ['LeftFoot', 'RightFoot'] if t in tags]
    error = float(np.linalg.norm(world[:, supports, :3] - source[:, supports, :3], axis=-1).max()) if supports else None
    if error is None or error > 1e-8:
        raise ValueError('standing goal did not retain both observed support feet')
    return world, {'kind': 'authored_standing_upper_body_goal', 'chain': chain, 'copied_joint_indices': copied,
                   'support_position_change_m': error, 'local_translations_preserved': True,
                   'scope': 'Measured upper-body configuration in the current observed stance; not a claim of executed target or object contact.'}
