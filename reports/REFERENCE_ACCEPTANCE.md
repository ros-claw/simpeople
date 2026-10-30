# Reference environment acceptance (v0.1)

These are historical closed-run results from the original implementation. They remain distinct from the revision-specific optimization report and do not certify every later code or motion-quality change.

Reference runtime: Isaac Sim `6.2.0-rc.14+release.52805.02189a84.gl`, Behavior/Navigation 110.4.0, NVIDIA A6000. The character pool contained 12 base rigs, 24 appearances and seven roles. NVIDIA asset data and multi-gigabyte raw run archives are not redistributed in this source repository.

| Closed run | People | Sim seconds | Minimum role cycles/person | RTF | Successful / failed / shutdown cancellation |
| --- | ---: | ---: | ---: | ---: | --- |
| p4-industrial-10-07 | 10 | 600 | 3 | 0.288891 | 55 / 0 / 9 |
| p5-industrial-30-06 | 30 | 900 | 1 | 0.182840 | 188 / 1 / 30 |
| p6-industrial-50-03 | 50 | 600 | 2 | 0.200381 | 159 / 5 / 50 |
| seed50-17-03 | 50 | 600 | 2 | 0.222814 | 175 / 1 / 48 |
| seed50-99-03 | 50 | 600 | 2 | 0.225180 | 177 / 4 / 49 |

All five met their recorded functional population gates without suspended actors or sustained root-proxy overlap/jump flags. Failures and shutdown cancellations are retained; the result was never “every task succeeded.” Fifty people were a generation capacity, not real-time operation.

The 100-person/120-sim-second case was exploration: 89/100 actual roots moved more than 1 m from their first ready position in the episode. It did not establish full all-person activity cycles. Cumulative idle sway or reset relocation cannot establish movement participation.

The original delivery source was `15f5a46e60682438e251ef1fb450471bc702d6ce`; its full native 50-person seed evidence used a common runtime implementation. The original source archive SHA256 was `7deef3f0144e6cf52150c33f80975911a3d77789cacbfe841ae7d069cb26f763`; evidence archive SHA256 was `1c11cf6ccf944d256cafd80b80c15e00f0f95fed627fd2dbf72ed6bde5f5749c`. These identify local sealed reference artifacts, not files bundled with this public checkout.

Original control acceptance included real CLI and stdio MCP, goal replacement, cancellation, pause/resume, reset, seat contention, dynamic obstacles, and Kit extension attach/unload with the original root layer preserved. The original MCP interface had 18 tools; the optimization adds compact session/crowd management to make 20.

Original geometry was based on actual runtime roots/radii and conservative proxies. It did not establish exact foot contact, whole-body mesh clearance, force balance or robot depth/LiDAR. The optimization report describes new foot-proxy and head/neck vertex checks separately.
