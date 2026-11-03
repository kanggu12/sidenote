## What and why

<!-- What this changes, and the problem it solves. Link the issue: Fixes #123 -->

## How it was tested

<!-- The checks you added or ran. The hardware you tried it on, when it matters. -->

## Checklist

- [ ] `./sidenote qa` passes (or the group this touches: `./sidenote qa server`, `./sidenote qa panel`)
- [ ] The new behavior has a check that fails without the change
- [ ] Words people see go through `t()`, with the Korean in `panel/i18n/ko.js` or `server/locale/ko.json`; in the
      launcher, `L` with both languages; in `client/capture.py`, `client/launch.pyw` or `desktop/app.py`, their `KO` table
- [ ] The docs say what changed for the person running Sidenote
