# Platform04 director's cut: first-round production

The 90-second / 24-character director kit is a production plan. This round
delivers the four requested review pieces before the human comprehension gate:
9-second silent opening, six-layer formal running comparison, 12-second
character reel, and 10-second continuous door chase. The full film is not rendered.

The input ZIP SHA-256 is
`61293c1070195a97c390faef056d84c3a583f810ba0384f991829a4472c44552`.
The PDF and both source audition videos were inspected. Proxy auditions are not
formal-actor validation.

`local_pose.py` mixes parent-local quaternion rotations with fixed long-bone
translations. Root and Hip translations remain permitted. The previous film's
world-XYZ blending really shortened limbs; actual USD FK restoration of all
540 old frames confirms the issue (`platform04-90-baseline-02`). This new film
uses ordinary Native Jog as its healthy cache base, with explicit source-phase
normalization only in the diagnostic Sprint/Jog comparison. It does not add a
Native sprint capability.

`platform04_90_director.py` owns the cinematic actors exclusively. Opening
cameras use the supplied opening stage. Moving characters advance fitted phases
by root distance; slow walking must not mix away the leg excursion while retaining
the full fitted travel. Brief purposeful infection actions do not pin an arm
through the entire run. Braking, turning, reach and recovery need RGB review in
addition to bone-length checks. A bounded shoe-height correction prevents visible
floor penetration without suppressing flight phases; it is not contact dynamics.

`platform04_90_observation.py` reads actual USD joints and deformed meshes.
Rendered leaf-ID pixels are divided by a same-camera, same-pose isolated triangle
silhouette, not a bounding rectangle. Fixed per-shot surface markers support the
provided actor-level freeze heuristic. Small, occluded, short or marker-poor
intervals remain unjudged; no whole-frame duplicate test can certify background
performance. Opaque CPU silhouettes do not reproduce hair alpha or glass optics.

`platform04_90_geometry.py` checks three foreground actors at 120 Hz near the
door. `linear_sweep.py` / `linear_sweep_cpu.cpp` check vertex-face and edge-edge
cubic events for linear vertex motion between samples. Coplanar unresolved cases
are explicitly not certified. This is not nonlinear articulated CCD or PhysX
contact. Background pairs and self-collision are outside this audit.

Reproduce with unique run IDs and the existing local NVIDIA assets:

```bash
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/platform04_90_shoot.py --run-id UNIQUE --mode door --gpu 2
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/platform04_90_geometry.py --run-id UNIQUE_GEOMETRY --gpu 3
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/platform04_90_nav.py --run-id UNIQUE_NAV --gpu 3
PYTHONPATH=src python3 -m pytest -q tests
```

The native run-time is 6.2.0-rc.14, Behavior/Nav 110.4.0. CPU RGB readback and one
synchronous 1/30-second step per recorded frame are retained. C++ sweep acceleration
requires g++; silhouette compilation requires gcc. Frozen snapshots and explicit
source-frame maps identify every selected frame. No source video is retimed to
stretch it into 90 seconds. AAC Foley is separately synthesized editorial sound,
using actual ankle minima as timing proxies, not measured contact impulses.

Local delivery: `productions/platform04_directors_review/START_HERE.html`.
Human blind viewers: **0**. The supplied kit asks for five independent viewers,
at least four understanding the three relationships before full-film production.
No responses or naturalness/scariness acceptance are fabricated. Prior ordinary
Native Jog pursuit and all old films remain separate and unchanged. The new
cinematic footage does not establish Native infected sprint, autonomous packs,
or a new Agent/MCP end-to-end capability.
