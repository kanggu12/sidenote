# `python -m desktop` from a checkout, and the entry of the Windows app's executable (desktop/build.py).
# An absolute import: the executable runs this file as a plain script, with no package around it.
from desktop.app import main

if __name__ == "__main__":
    raise SystemExit(main())
