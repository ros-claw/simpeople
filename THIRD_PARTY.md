# Third-party dependencies and assets

The MIT license covers the SimPeople code authored in this repository. It does not relicense Isaac Sim, NVIDIA Behavior/Navigation, NVIDIA characters, motion libraries, textures, or third-party Python dependencies.

Isaac Sim and its extensions must be installed separately. The cache preparation script references NVIDIA's official Behavior sample asset source and writes a local manifest of source URLs and hashes. Asset data is excluded from Git and from source packages. Additional Isaac people are referenced from the user's installed asset directory. No NVIDIA model, motion clip, texture, SDK binary or SDK source is redistributed here.

Python dependencies retain their own licenses. Exact versions used in the reference environment are recorded in requirements-controller.txt. Video capture invokes the system ffmpeg executable; ffmpeg is not bundled.

Curated PNG/MP4 illustrations are rendered outputs of the reference simulation, not model or motion source data. Their inclusion does not grant a license to the separately installed NVIDIA assets. Full raw run archives remain local; only the explicitly selected demonstration renders are exported.
