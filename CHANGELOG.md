# Changelog

What changed in each release of Sidenote. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/): a release that adds something raises the minor number, one
that only fixes raises the patch number. Each release's section here is its release notes.

## [Unreleased]

### Fixed

- With the panel in English, the prompt's example of an answer's one line is English as the answer is, where it stayed
  Korean. Measured with the panel in English, the line asking for the point of an answer (0.4.0) keeps the same answers
  right and leaves no line that only names the question's topic (3 of 42 before it).

## [0.4.1] - 2026-11-08

### Fixed

- The setup guide's sample problem ends whatever becomes of it: an error, a call-off or a dropped connection left
  "Solving the sample problem" until the page was loaded again, and the sample opened a second time (a problem solved
  before) now has that answer. With Practice on, the guide no longer shows the answer the notebook keeps back, and an
  answer with no head line no longer counts as no problem found.
- The setup guide keeps an open list, the screen it shows and the words in a box while the server talks, where the
  screen step drew itself again every second; a screen asked for after it closed starts no drawing on the screen card.
- A folded spoken answer keeps the end of what was heard, the question, where a narrow window cut it off; **Show it
  all** stands under a text only when it does not fit, a text opened whole stays so when its answer is drawn again,
  and Korean words heard break between words.
- A summary is not split inside a **bold** pair, a code span or math, nor after Dr. or Mr.
- On a phone a spoken problem's "heard by voice" stands on its own line under the answer's keys, which keep their place
  on the date's line; a choice's keys stand in even columns on a narrow sheet; the capture card's values line up in
  English; and with the server gone the welcome ticks no engine as connected.
- The Local model card's GPU keys read **Free GPU** and **Load to GPU** in English: beside the longer words its pill was
  cut to "On GP" in a column 300 pixels wide.
- The desktop shortcut's windows: a failure keeps a long line of the launcher whole, the reason being at its end; the
  note of a start already under way stands above that start's window, where it covered it; no dot at the window's
  corner before the groove fills; the later steps' shadow follows their round ends; and with no Pillow the steps keep
  their check and dots. The shortcut gives the window the server's port (`SIDENOTE_PORT`), where it waited on 8777:
  `./sidenote shortcut` makes it again.
- The sample problem draws its choices ① to ④ at the text's size, where the font's own marks were a third of it.
- The macOS quick start restarts Sidenote in a block of its own, once Screen Recording is on, and the user guide's
  pictures name the agent as the panel does.

## [0.4.0] - 2026-11-08

### Added

- A **Setup guide** in the panel, in four steps: what solves (the local model and the agent as their cards say them),
  the screen (the one the server receives, the monitor, **Skip windows**), the sound, and a sample problem to try,
  followed to its answer. Each step is ticked once what it is about works, and holds the rows of **Solver settings** it
  is about. It opens by itself the first time a panel meets a server that has kept no answer, and from the gear menu.

### Fixed

- The one-line answer to an explanation or a comparison is its answer. The local model could write the question's
  topic there, and a folded answer then showed that alone, as if the answer had been cut off.

## [0.3.0] - 2026-11-08

### Added

- The **Local model** and **Agent** cards fold to their top line on a press of their name, and stay so in the browser.

### Changed

- Notices look the part. The toast at the top of the panel and the question box at its foot are glass the page shows
  through, where they stood opaque; the toast's kind is in its mark alone. The desktop shortcut's windows are drawn as
  the tray menu is, in its colours and language: the start's steps as pills over a groove that fills as the start goes
  and is full at its end, and a failed start, or a second click while one is going, in that same window, with the
  launcher's last lines to select and copy. Windows' own message box is left for a Python with no tkinter.
- An answer reads at a glance. A spoken problem's **Heard** row is what was said, three sentences a paragraph, its first
  lines when it is long and the whole on **Show it all**; folded, an answer with no question line keeps the end of what
  was heard, where it showed its summary alone. A summary of several sentences marks its first, the point, and gives the
  rest a line each, where all of it was one marked block.
- The README's quick start installs Sidenote on its own, a few lines for each system: the local model and the cloud
  agent each have an optional part (either one solves, and one is needed), and the Kubernetes install moves to the
  user guide.
- The README opens with four of Sidenote's views (an answer, what was heard, the solver settings, the capture), and the
  user guide gains the shortcut's windows, the voice flow and a figure of what to check when no answer comes.

## [0.2.2] - 2026-11-07

### Changed

- The README's quick start is one block of commands for each system, to paste as it is; the user guide's first steps
  follow it, with the browser's download as the other way. The guides say what the app does on macOS where they named
  Windows and Linux only, and what `SIDENOTE_EFFORT` and `SIDENOTE_LANG` do as they do it.

### Fixed

- With Docker on a Mac, `./sidenote login` and `doctor` said the server used the Mac's Claude Code login, which the Mac
  keeps in the Keychain, out of the container's reach: the server was not signed in. There `./sidenote login` makes a
  token with `claude setup-token`, keeps it in `.env` as `CLAUDE_CODE_OAUTH_TOKEN` and starts a running server again
  with it.
- The app's server, ended with SIGTERM (as when the app dies, or when asking it to close down does not work), skipped
  its clean-up: the agent's CLI writing an answer went on, and that answer's screens stayed in the temporary folder.
- Started again within its first seconds, the app put two panels up: the copy starting opened its own, and the second
  start one more. The second start opens one only when the first brings none up (started with `--no-browser`).
- The app ran the code check on every coding answer although it has no code runner: this PC's model read the problem's
  examples, and then each answer was marked as failed. With no runner there is no check.
- An answer to a problem asked aloud, or to **Reanalyze**, was kept under the time of the last screen, minutes earlier:
  out of order in the history, and out of **Practice**'s reach. It is kept under the time it was asked.
- **Clear history** in one panel left the other open panels showing the answers, and a star pressed there was refused.
  Every open panel now clears.
- A panel opened or reloaded while an answer was being written showed nothing of it until it was done. It shows the
  answer as written so far.
- Opened with answers kept, the panel stood short of its end, the newest answer's follow-up keys half under the question
  box.
- Term cards stood two to a row on a narrow window, and in the thread beside the column on a window of about 1,000 to
  1,150 px, at 150 to 290 px each, their code broken inside an option. Each takes its row there.
- The agent's usage-limit band was green, the colour of a connected engine, and with the local model off a red "every
  engine is off" band stood beside it. It is orange like the agent's card, or red when nothing answers meanwhile, and
  alone.
- A command's caption named its first word ("Command 1. sudo", "Command 2. #"); it names the program it runs.
- The local model's card in trouble said what was wrong a second time under its own label; it says what to do.
- The heard sheet's times were the panel's only 24-hour ones. Outside the code blocks' own bars the small keys came in
  three heights (24, 26 and 28 px) and the search field stood 2 px taller than the filters beside it; the settings
  sheet's rows changed height with their control, two of the column's card titles sat 3.5 px high, and on a narrow
  window a band's words were squeezed beside its key.
- Korean: the agent's name took the wrong particle ("Claude Code이"), three lines read as sentences where the panel
  speaks in short phrases, and a loading step wrapped.
- Markdown export: an answer's own headings stood level with the answers'; they go two levels under each answer.

## [0.2.1] - 2026-11-07

### Fixed

- On macOS, opening Sidenote again while it runs opens the panel, as starting it again does on Windows and Linux. macOS
  tells the copy that runs instead of starting another, and nothing answered it. CI now opens the built app there as
  the Finder does, opens it again and quits it as macOS does at log out.
- Starting the app while it was still closing down did nothing: it waited for that copy's server, which was not coming
  back. It now waits for that copy to end and starts in its place.
- A quit could take up to 10 s, after which the app ended its server the hard way: the server waited for jobs still
  running on its threads, such as the first start's download of the speech model or the question to the agent's CLI of
  which model it runs on. The app's server now ends as soon as its own close-down is done (0.4 s, from 11.1 s during
  the download), and a download cut off this way is made again at the next start.
- The capture program's lines reached `capture.log` in blocks of 8 KB, and on macOS a quit sent by the system lost the
  ones not yet written. Each line is written as it is printed.

## [0.2.0] - 2026-11-07

### Added

- The app for macOS: `Sidenote-macos-arm64.zip` holds `Sidenote.app`, for macOS 14 or newer on Apple silicon, with its
  icon in the menu bar. It is not signed by a publisher yet, so the first time macOS blocks it until you choose **Open
  Anyway** in **Privacy & Security** (the README says how). CI builds it on macOS 15 and starts it there with its
  server, and its capture program sends a screen, reads the windows and quits when asked; outside CI it has not been
  used on a Mac yet.
- Apple silicon counts as the GPU the local model runs on. It is read as the share of the Mac's memory macOS lets the GPU
  keep, so the panel offers `gemma4:e4b` on a Mac of 16 GB or more and `gemma4:26b` from 32 GB. How fast and how well
  the models answer on a Mac has not been measured yet.

### Fixed

- The capture program on macOS ran its tray icon off the main thread, which AppKit does not allow; it runs it on the
  main thread and captures beside it. **Skip windows** and the cover over the panel's own window read macOS's window
  list there: they had tried X11 and skipped nothing.
- The app opened from the Finder or a desktop's menu starts with a short `PATH`, so Claude Code, Codex or an Ollama from
  Homebrew, found in a terminal, seemed to be missing. It asks the login shell for its `PATH`, with a time limit, and
  looks in the agents' usual folders. On macOS with no locale set, its messages follow the system's first preferred
  language (Korean or English).
- The panel: on a wide window the bands that did not fit in the bar floated over the first answer. They take their room
  above the thread when the page is at its top and keep it while it scrolls, so the thread moves only by the scroll.
- Korean: a chip with a command in it takes no particle after the command.
- Six list items in the README, the user guide and CONTRIBUTING showed as an empty item with the text nested below it.

### Removed

- The winget package's manifests and the release job that tried them: Sidenote is installed from the zip on its
  releases, as the README says.

## [0.1.8] - 2026-11-07

### Fixed

- The turn of a problem's box written y first, added in 0.1.7, turned nothing in the server: it read the screen as a
  picture, and the server holds it as the PNG that arrived. It reads that now, and leaves alone a box against the screen's
  own edge, where it could not tell. Through the server's own path, over 559 first-pass boxes from earlier runs, it turned
  6, each from at most a quarter of its problem to most or all of it, and none that held its problem
  ([note 107](https://github.com/kanggu12/sidenote/blob/main/docs/DECISIONS.md#note-107)).
- The panel, from 0.1.7: where the bands fit in the bar, a small scroll took them out of it and moved the thread down by
  their height; above 1000 px they float again, and in one column they take their room and scroll inside themselves past
  a third of the window. Solver settings runs past the window no more under a bar of two rows or in a short window.
- The contents' search finds an answer's code as it is written (`__init__`, `$files`), and no longer a chart's numbers or
  a diagram's source after a blank line in it; a table's rule and a formula's environment names are gone from its rows.
- A review of starred answers keeps back a starred answer that the Starred choice brings in from the server, opened
  before.
- **Keep answers** and **Keep what is heard** give the days and megabytes the server is set to, not fixed ones.
- What a press opens at the foot of the page comes into view as the panel's own scroll, so an answer chosen in the
  contents stays chosen. A toast's bold part no longer ends inside brackets, and at 1000 px and below a toast is as wide
  as the bands.
- Korean words: an answer seen again reads "새로 풀려면 다시 분석", and the welcome's tip has no particle after its chip.

### Changed

- How a release is numbered is written down ([CONTRIBUTING](https://github.com/kanggu12/sidenote/blob/main/CONTRIBUTING.md#release-a-version)):
  a release that adds something raises the minor number, one that only fixes raises the patch number.

## [0.1.7] - 2026-11-07

### Fixed

- A problem's box the local model wrote y first, up to twice as tall as wide, is turned when the picture shows it: its
  edges cut through the lines of text and the turned box's do not. Over 495 boxes from earlier runs, 5 were turned, each
  from at most a quarter of its problem to most or all of it, and none that was right
  ([note 107](https://github.com/kanggu12/sidenote/blob/main/docs/DECISIONS.md#note-107)).
- The panel: at 1000 px and below a band at the top of the page lay over the first answer, whose keys could not be pressed;
  it now takes its room. A hint, the answer or the details opened on the newest answer came up under the question box,
  and now come into view. The contents' rows and their search read an answer's words, not its Markdown, diagram source
  or TeX. Solver settings keeps one height for every section, so Reset to defaults stays where it is.
- Korean words in the panel: a sequence diagram is named as one (it was called a flowchart), no particle stands apart
  from the Reanalyze chip, and Practice's choices come in the order Motion's do.

### Changed

- The README says what a PC needs for each model (GPU, memory, disk), with what was measured on the test PC, and the
  guides say the Mac where they named only Linux, with a few facts put right and sentences made plainer.
- The guide starts vLLM with Gemma 4's picture budget at 1120 tokens, as Sidenote runs Ollama: Gemma 4 E4B there went
  from 30 of 56 to 39, against Ollama's 38. llama.cpp's server gets the same budget
  ([note 108](https://github.com/kanggu12/sidenote/blob/main/docs/DECISIONS.md#note-108)).
- Measured and written down: **Think before answering** stays on Auto
  ([note 109](https://github.com/kanggu12/sidenote/blob/main/docs/DECISIONS.md#note-109)), and Qwen3-VL 30B got 18 of 56,
  so it is not suggested ([note 110](https://github.com/kanggu12/sidenote/blob/main/docs/DECISIONS.md#note-110)). On
  llama.cpp's server, Gemma 4's multi-token prediction head made the 26b about a tenth faster
  ([note 111](https://github.com/kanggu12/sidenote/blob/main/docs/DECISIONS.md#note-111)).

## [0.1.6] - 2026-11-07

### Added

- Docker on a Mac: `./sidenote` runs on macOS's own bash 3.2 and BSD tools, the capture program reads the Mac's screen
  and records from a loopback input such as BlackHole (and says how to get one when there is none), and the local model
  runs in Ollama for Mac. CI checks all three on macOS. The README says how to start.
- The server image fetches Claude Code and Codex for the machine it is built on, so it builds on arm64 (Apple silicon,
  ARM servers); CI builds both images on arm64 too.
- A review of starred answers: with **Practice** on, choosing **Starred** in the contents keeps every starred answer
  back, however old, to be opened hint by hint.

### Changed

- Every notice in the panel has one form. A toast is drawn as a band is: a mark for its kind (to know, done, not done,
  failed), the fact in bold, then what follows or what to do, and a command as a chip. Its colors are the bands' own, and
  it stays longer when it says more. The server says which of the four kinds each of its notices is.
- The help for nine settings is a sentence or more shorter.
- The Anthropic API agent marks its instructions for the API's prompt cache: while problems come within five minutes of
  each other, those 1,300 or so tokens are read from the cache at a tenth of the price.
- The same web search or page within ten minutes is answered from memory, without asking the search engines again.
- The README puts the quick start before the reasons for Sidenote.
- The README's badges are files in the repository (`.github/badges.sh`), so none waits on another site, and its picture
  of the panel and the user guide's numbered one show the panel as it is now. The README gathers everyday commands in a
  table of its own.

## [0.1.5] - 2026-11-06

### Fixed

- A model that `./sidenote llm pull` or the chart's pull job makes carries Sidenote's context, as one the panel downloads
  does. Loaded by an Ollama that Sidenote did not start, such as the one Ollama's installer starts at sign-in, it had that
  Ollama's 4096 tokens.
- On a model server other than Ollama, Sidenote turns the model's thinking on and off through its chat template
  (`enable_thinking`), as it already did through Ollama. llama.cpp's server thinks by default, and Gemma 4 E4B took 7 to
  8 s there to call a screen empty; vLLM does not, so a pass meant to think did not.
- A model server that turns down a request for its tools, as vLLM does when started without its tool-calling switches, is
  asked again without them, and the local model there answers without web search. Before, every answer there failed.
- The README's release badge names the version itself. The one shields.io looked up from GitHub came slower than
  GitHub's image proxy waits, and showed as a broken picture.

### Changed

- With `SIDENOTE_LOCAL_URL` naming another model server, such as vLLM or llama.cpp's server, `./sidenote up` leaves the Ollama
  container out, and `./sidenote llm` and `./sidenote install` say the models are that server's.
- The panel: on the dark theme the red pen is brighter (5.3:1 against the paper, from 4.4:1); on the light theme the punch
  holes read as holes, not as empty radio buttons; the kind chips line up with the labels at 821 to 1000 px; the star keeps
  its place beside Copy all; a chosen option looks pressed in; a table's number column takes its numbers' width; the
  keyboard shortcuts sheet speaks in short phrases; and Reset to defaults looks like a button.
- The README is shorter, with a quick-start table, and the user guide's first steps say which folder holds the app and
  when to sign in to the agent.
- How to start vLLM for Sidenote (its reasoning and tool parsers), and how llama.cpp's server and vLLM compare with Ollama
  on the known-answer set: [note 108](https://github.com/kanggu12/sidenote/blob/main/docs/DECISIONS.md#note-108).

## [0.1.4] - 2026-11-06

### Fixed

- With the speech language on **Auto**, an English sentence of 3 s or more that the speech model is sure of stays English in
  a session that has been speaking Korean. Before, it was written down again as Korean: of 73 English sentences read aloud, 30
  came back as Korean that lost what was said, 12 of them as one phrase over and over. A shorter one is still written down as
  Korean, and no longer as one phrase repeated: the words before the repeat are kept.
- [Running with no internet](https://github.com/kanggu12/sidenote/blob/main/docs/air-gapped.md): the speech model goes in the
  bundle as plain files. Its cache keeps them behind links, which Windows unpacks only with Developer Mode on.
- On Kubernetes, the guide's pods unpack the bundle as their own files (`--no-same-owner`): their root, with most of its powers
  dropped, could not read files that kept the owner they had on the other PC.
- The guide also covers the app on Linux, an Ollama that runs as a service, the images the chart asks for, and a model server
  you already run, such as vLLM or llama.cpp's.

## [0.1.3] - 2026-11-05

### Added

- Running with no internet: [a guide](https://github.com/kanggu12/sidenote/blob/main/docs/air-gapped.md) to carrying the
  images, the models and the capture packages to a closed network, `SIDENOTE_OFFLINE=1` so that `./sidenote up` builds and
  pulls nothing, and `SIDENOTE_WHEELS` for `./sidenote setup-capture`. Cloud agents and web search cannot work there, and the
  guide says so.

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

[Unreleased]: https://github.com/kanggu12/sidenote/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/kanggu12/sidenote/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/kanggu12/sidenote/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/kanggu12/sidenote/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/kanggu12/sidenote/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/kanggu12/sidenote/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/kanggu12/sidenote/compare/v0.1.8...v0.2.0
[0.1.8]: https://github.com/kanggu12/sidenote/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/kanggu12/sidenote/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/kanggu12/sidenote/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/kanggu12/sidenote/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/kanggu12/sidenote/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/kanggu12/sidenote/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/kanggu12/sidenote/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/kanggu12/sidenote/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/kanggu12/sidenote/releases/tag/v0.1.0
