"""Film skeletal interpolation with fixed anatomy and parent-local rotations.

Pure NumPy: usable by offline audits without importing Kit. World-position
interpolation is deliberately absent; it shortens long bones during transitions.
"""
from dataclasses import dataclass

import numpy as np

from .deadweight_cinema import inverse, quat_apply, quat_mul


def slerp(a, b, weight):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float).copy()
    a = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b /= np.linalg.norm(b, axis=-1, keepdims=True)
    dot = np.sum(a * b, axis=-1, keepdims=True)
    b = np.where(dot < 0, -b, b)
    dot = np.clip(np.abs(dot), 0, 1)
    theta = np.arccos(dot)
    sine = np.sin(theta)
    safe = np.where(sine > 1e-8, sine, 1)
    result = np.sin((1-weight)*theta)/safe*a + np.sin(weight*theta)/safe*b
    result = np.where(sine < 1e-8, (1-weight)*a+weight*b, result)
    return result / np.linalg.norm(result, axis=-1, keepdims=True)


@dataclass
class LocalPose:
    translations: np.ndarray
    rotations: np.ndarray


class FixedAnatomy:
    def __init__(self, names, reference_positions, reference_rotations,
                 free_translation_leaves=('RL_BoneRoot', 'Hip')):
        self.names = list(names)
        indices = {name: i for i, name in enumerate(names)}
        self.parents = np.array([indices[n.rsplit('/', 1)[0]] if '/' in n else -1
                                 for n in names], dtype=int)
        if any(p >= i for i, p in enumerate(self.parents)):
            raise ValueError('joints must be in parent-before-child order')
        depth = []
        for p in self.parents:
            depth.append(0 if p < 0 else depth[p]+1)
        self.levels = [np.flatnonzero(np.array(depth) == d)
                       for d in range(max(depth)+1)]
        self.free = np.array([p < 0 or n.rsplit('/', 1)[-1] in free_translation_leaves
                              for n, p in zip(names, self.parents)])
        reference = self.from_global(reference_positions, reference_rotations,
                                     normalize_anatomy=False)
        self.reference_translations = reference.translations.copy()

    def from_global(self, positions, rotations, *, normalize_anatomy=True):
        p = np.array(positions, dtype=float, copy=True)
        q = np.array(rotations, dtype=float, copy=True)
        q /= np.linalg.norm(q, axis=-1, keepdims=True)
        translations = p.copy()
        rotations = q.copy()
        children = np.flatnonzero(self.parents >= 0)
        parents = self.parents[children]
        parent_inverse = inverse(q[parents])
        translations[children] = quat_apply(parent_inverse, p[children]-p[parents])
        rotations[children] = quat_mul(parent_inverse, q[children])
        if normalize_anatomy:
            translations[~self.free] = self.reference_translations[~self.free]
        return LocalPose(translations, rotations)

    def forward(self, pose):
        p = pose.translations.copy()
        q = pose.rotations.copy()
        for ids in self.levels[1:]:
            parents = self.parents[ids]
            p[ids] = p[parents] + quat_apply(q[parents], pose.translations[ids])
            q[ids] = quat_mul(q[parents], pose.rotations[ids])
        return p, q

    def blend(self, a, b, weight):
        if not 0 <= weight <= 1:
            raise ValueError('blend weight outside [0, 1]')
        translations = self.reference_translations.copy()
        translations[self.free] = (a.translations[self.free]*(1-weight)
                                    + b.translations[self.free]*weight)
        return LocalPose(translations, slerp(a.rotations, b.rotations, weight))
