"""The version of Sidenote this code is, in one place.

The server reports it (/health, the panel's status) and compares it with the latest release (server/updates.py); the
launcher prints it (`./sidenote version` reads the line below as text); and the release workflow refuses a tag that is
not "v" and this number, or a Helm chart whose version and appVersion differ from it (.github/check_version.py).
Before tagging a release, set it here and in deploy/helm/sidenote/Chart.yaml.
"""

# MAJOR.MINOR.PATCH, as semver.org writes it; the line is read as text, so it stays one line in this form
VERSION = "0.9.0"
