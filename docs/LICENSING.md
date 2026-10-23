# Licensing and attribution audit

No original-work license is assigned by this cleanup. Public visibility alone does not grant a reuse license. The owner must approve a license and confirm ownership of the original report/code before a license is added.

Recommendation for that decision: MIT for original software, and CC BY 4.0 for the original report, figures and measurement tables. This permits broad reuse with attribution and distinguishes software from research material. These are proposals, not effective grants. No LICENSE file or new SPDX claim is added.

## Third-party material

- The tcconfig 0.30.1 compatibility patch is accompanied by the existing [MIT notice](../experiment/compat/LICENSE.tcconfig), including Tsuyoshi Hombashi's attribution. Preserve it with the patch and any upstream portions. [Release metadata](https://pypi.org/pypi/tcconfig/0.30.1/json) declares MIT; no full tcconfig distribution is vendored here.
- MADT is downloaded at runtime from [revision ca7df8460448ae515f17bfb3a594b30ef9503415](https://github.com/dltcspbu/madt/tree/ca7df8460448ae515f17bfb3a594b30ef9503415). Inspection of its recursive tree found no LICENSE/COPYING/NOTICE file, and its README contains no license declaration. Do not infer a license from its GitHub visibility. This release references/downloads MADT rather than redistributing its source; licensing clarification is needed before vendoring or relicensing upstream MADT code.
- Lima, Ubuntu images/packages, Docker/containerd, Python packages, TeX and PDF-build dependencies are obtained separately under their upstream terms. Their package pins are not a relicensing of those dependencies. This repository does not ship their binaries or font files. If a future release bundles them, audit their individual notices and redistribution terms then.
- Wang et al. is cited as literature. Its article, figures and code are not redistributed here. The topology is the original report's diagram, not an imported Wang figure.

Audit source dates: 23 October 2026. tcconfig wheel SHA-256 from PyPI: `a2a2f127ce075c691760503561be4d06eb92f2d4e92ec8dd393cf3e30cc15d68`; source archive `71026a22d2be180ff7e251b860e448029d1dd3f5a3be1a11b1a19b4ccb4bbf60`. Neither artifact is added to this repository. Original upstream notices already present in the measured payload remain byte-identical.
