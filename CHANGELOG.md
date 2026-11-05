# Changelog

What changed in each release of Sidenote. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/). Each release's section here is its release notes.

## [Unreleased]

## [0.1.2] - 2026-11-05

### Changed

- **Skip windows** stops the screen while a window named in the list shows on the monitor being captured, whichever
  window has the focus. One minimized, on another desktop or wholly covered does not stop it, and the panel never does.
- `./sidenote install` ends well on a first run: no model and no login are named as what comes next, and only what is
  really missing fails it.
- `./sidenote uninstall` also lists and removes the Ollama and SearXNG images, except one another project is using, and
  says what it leaves.
- The containers' log times and days follow this PC's time zone (`TZ` in `.env` first), and the chart's default is UTC.

### Fixed

- A problem's box the local model wrote y first, which reads as a tall strip somewhere else on the screen, is read the
  right way round, so its crop holds the problem.
- With Docker on a PC whose user is not root, the server runs as that user: it reads the agents' logins, which it could
  not do before, and the log folder stays the user's. A folder an earlier version gave to root comes back at the next
  `./sidenote up`.
- What is heard no longer goes missing while the live line is written: a sentence caught in mid-word could send the
  speech model round on one sound for a minute, and whatever was said meanwhile, a question among it, was lost.
- English after Korean is read as English sooner, and a sentence held to Korean no longer takes the speech model's
  retries, which could hold up what came next.
- A spoken question waiting behind a long answer is still asked when that answer ends; it could age out and leave an
  analysis of the screen with no words in its place.
- Practice's hints stop before the answer however it is written: a heading with bold or a number, a heading of a lower
  level, a list item, or a line such as "정답: ③". A heading that only mentions the word, such as "Answer format", no
  longer ends the hints.
- With Practice on, the thinking line is not shown while an answer is being worked out, and a `$$` in inline code no
  longer runs the rest of a solution into one hint.
- The screen card says when **Skip windows** cannot read all the windows on this desktop (**Windows not skipped**,
  **Front window only**). A read of the windows that fails is tried again at the next look.
- The desktop shortcut `./sidenote shortcut` makes wears Sidenote's icon, not Windows' printer. Run the command again to
  change a shortcut already made.
- `./sidenote shortcut` works when the Windows desktop's path holds Korean, such as OneDrive's 바탕 화면.
- A local model server that is still starting is no longer called "not responding", by `./sidenote up` or in the panel.
- `./sidenote` says when `python3` is missing, instead of ending with no message.
- `history.sqlite` and a log folder the server creates can be read by their user alone.
- What is heard and the answers past their age go at the server's start, not only after six hours of running.
- Choosing a speech model while the first one loads no longer starts a second speech worker.
- A short spoken question with no question mark is taken ("정답은 뭘까", "List joins."), and a sentence about work done
  ("출력하는 부분을 고쳤습니다") no longer starts an analysis at once.
- `h` and `a` show their part at once when words are selected in the answer.
- Opening the list of keys or **What was heard** closes an open dropdown, and both lists scroll from the keyboard.
- `Esc` leaves the contents' search and keeps its words. The letter keys do nothing while a region is being drawn.
- The keyboard goes back to **Export** from the list of keys opened in its menu, and stays on the page after a
  new-version line is closed.
- A carriage return in an answer no longer breaks a line of the Anki file.
- The chart's README installs the current release, and its notes give a model download that works with the published
  chart.
- A pre-release tag publishes as a pre-release, with no `latest` images and no winget package.
- The capture program's zip holds the picture its README shows.

### Security

- The winget token reaches only the step that sends the package, and that step runs one pinned release of wingetcreate,
  checked against its checksum.

## [0.1.1] - 2026-11-05

### Added

- Practice mode (**Practice** in the gear menu): an answer arrives folded, with **Show a hint** for its sections one at
  a time and **Show the answer** for the rest.
- Keyboard shortcuts: j and k move between answers, c copies the answer line, r reanalyzes, p pauses, / searches the
  contents, and ? lists them all.
- Export to Anki: the contents' **Export** saves the answers shown as notes for Anki, the question on the front and the
  answer line with its key point on the back.
- Starred answers: a star on each answer, a **Starred** choice in the contents, and starred answers are kept past the
  history's limits.
- **Skip windows** in Solver settings: while a password manager, a private browser window or any window named in the
  list is in front, the capture program sends no screen.
- **Keep what is heard** in Solver settings, off by default: every sentence heard is kept on this PC with its time, and
  **What is heard** opens a day's lines to copy or save.
- **Extra terms** and a choice of speech model (small or medium) in Solver settings. Technical terms are given to the
  speech model as hints in both languages: of 146 terms in the test recordings, 124 come out right, against 103 before.
- A line in the panel when a newer release is out, checked once a day (**Check for new versions**, on by default;
  `SIDENOTE_UPDATE_CHECK=0` turns it off for good). The panel's gear menu and `./sidenote version` show the running
  version.
- Each release lists the SHA-256 of its files in `SHA256SUMS`, and GitHub records where each file was built
  (`gh attestation verify`).
- [Discussions](https://github.com/kanggu12/sidenote/discussions), for questions and ideas.

### Changed

- The Linux app is built on Ubuntu 22.04, so it runs on glibc 2.35 and newer (0.1.0 needed 2.38).
- The capture program's tray icon is the wordmark's S over the highlighter.
- The CI check before `./sidenote up` is for maintainers: it runs only with `SIDENOTE_CI_GATE=1`.
- `./sidenote setup-capture` sets up the capture program on Linux too; `setup-windows` stays as another name for it.
- Sentences say "the local model" and "the agent"; the panel's labels read **Local model** and **Agent**.
- A spoken question is answered when it asks the listener something. A story, a tag such as "right?" and a question the
  speaker reports are not solved, and **What is heard** says under a sentence why it was not taken. A question counts
  from 6 characters, so "GTID가 뭔가요?" is answered.
- A newer spoken question waits behind an answer being written instead of cutting it off.
- A question heard is answered in the panel's language by both the local model and the agent.
- docs/ARCHITECTURE.md is an overview with tables and pictures; the design notes are in docs/DECISIONS.md.

### Fixed

- On Windows, quitting the app lets the server close down: what it keeps for the next start is written, so the screen
  still showing is not solved again.
- On Windows, the agent's CLI opens no console window, and a cancelled turn stops all of the CLI's processes.
- A turn cancelled before its request went out does not count toward the hourly cost limit.
- When the agent declines a screen, the local model answers it (on by default); when that fails, the agent's reply is
  shown instead of nothing.
- The answer line's **Copy** gives exactly what the line shows; English labels no longer run into each other; the five
  readings are back in the top bar on narrow windows.
- `./sidenote uninstall --yes` on Linux no longer stops at the shortcut step, and Docker's own error is shown when a
  command fails.

### Security

- The web pages the local model reads are fetched only from the address the name was resolved to and checked against,
  so a name that points at the local network by the time of the connection gets no request.

## [0.1.0] - 2026-11-04

The first public release: the app for Windows and Linux, the Docker setup, the Helm chart and the capture program.

[Unreleased]: https://github.com/kanggu12/sidenote/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/kanggu12/sidenote/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/kanggu12/sidenote/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/kanggu12/sidenote/releases/tag/v0.1.0
