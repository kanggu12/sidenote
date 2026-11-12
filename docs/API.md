# The API

Everything the panel does, a program can do over HTTP: read what the panel shows, change what the panel changes, and
follow what the panel is told as it happens. The API is part of the server that serves the panel, at `/api/v1` on the
same address, and it runs each change the way the panel's own controls run it. A key pressed in the panel and a call
to its route do the same thing and tell every open panel the same.

- [Reaching it](#reaching-it)
- [A first call](#a-first-call)
- [Answers and errors](#answers-and-errors)
- [Reading](#reading)
- [Changing](#changing)
- [Following: events](#following-events)
- [The panel's messages](#the-panels-messages)
- [Versions](#versions)

## Reaching it

The examples use the address the panel opens at, `http://127.0.0.1:8777` (`SIDENOTE_PORT` changes the port). The API is
reached the way the panel is:

- From this PC only. Docker publishes the port on this PC's loopback, the desktop app listens there, and the Helm chart
  is reached through `kubectl port-forward`, as its panel is.
- Not from another site's page. A browser says which page a request comes from, and one from any page but the panel's
  own is refused (`403`).
- Every request that changes something sends a JSON body with `Content-Type: application/json`, and `{}` when there is
  nothing to send. A page of another site cannot send one without asking the server first, which this server refuses
  (a `403`, with no CORS headers). A body that is not JSON, or holds what JSON does not (`NaN`, `Infinity`, a number past a float, a lone
  surrogate), is a `400`, and so is one nested deeper than any request is (some 450 levels).
- At `127.0.0.1` or `localhost` only: any other Host, `[::1]` and this PC's name included, is refused with a plain-text
  `400 Invalid host header` before the API sees it.

There is no key: what runs on this PC can use the API, as it can open the panel. Switch the server off, or stop the
container, to keep a program on this PC from it.

## A first call

```sh
curl -s http://127.0.0.1:8777/api/v1/status
curl -s -X POST http://127.0.0.1:8777/api/v1/pause -H 'Content-Type: application/json' -d '{}'
curl -s -X PUT http://127.0.0.1:8777/api/v1/settings/history_keep -H 'Content-Type: application/json' -d '{"value": true}'
curl -s -N http://127.0.0.1:8777/api/v1/events
```

`GET /api/v1` lists every route with what it does, and which of the panel's messages each runs.

## Answers and errors

Every answer is a JSON object with `ok`. On an error it has `error` too, in words to show a person.

| Status | When |
|---:|:---|
| `200` | Done, and the answer says how things stand now |
| `202` | Started: what it starts goes on in the server, and comes as [events](#following-events) |
| `400` | The request is not what the route takes: a missing or wrong value, a body that is not a JSON object |
| `403` | Sent from another site's page |
| `404` | No such route, answer, setting or waiting problem |
| `405` | The route takes another method; `methods` says which (`OPTIONS` and `HEAD` too) |
| `409` | Not possible now, and `error` says why (nothing answered yet to ask about, downloads off) |
| `413` | A body over 2 MB, refused as it comes in |
| `415` | A change sent without a JSON body |
| `422` | A code run that did not run: code runs are off, the sandbox is out of reach, or the code did not build (`error`) |
| `429` | 32 readers of events are open already, or 8 questions are being answered (`POST /api/v1/ask`) |
| `500`, `502` | The server, or the model server it asked, failed at it: `error` names what failed, and the server's log has why |
| `503` | The server has 512 connections open already: plain text from the server, not JSON; ask again once fewer are open |

The words in `error` and in a change's `notices` are the panel's own, in the panel's language.

## Reading

| Route | Gives |
|:---|:---|
| `GET /api/v1` | The API's version, its routes, and the route of each of the panel's messages |
| `GET /api/v1/status` | What a panel is shown as it opens: `status`, `settings`, `capture`, `usage`, the `confirms` waiting, the answers being written (`live`), and what the server is busy with (`activity`). Its `status` says where the server runs (`where`: `desktop`, `container`, `cluster` or `host`) and, in a cluster, the `namespace`, `service` and `port` of its port-forward (`forward`) |
| `GET /api/v1/settings` | Every setting's value (`values`), and what the settings sheet shows of each (`meta`: its words, its options, its default) |
| `GET /api/v1/settings/{key}` | One setting: `value` and `meta` |
| `GET /api/v1/answers` | The answers kept, the newest first. `?day=YYYY-MM-DD`, `?q=words` (every word in the answer, the question or the follow-ups), `?kind=essay`, `?starred=true`, `?limit=60` (at most 200) |
| `GET /api/v1/answers/{seq}` | One answer kept, by its id (`404` for one in **Recently deleted**) |
| `GET /api/v1/answers/deleted` | **Recently deleted**, the latest deleted first, at most 200: each answer whole, with when it was deleted (`deleted`) and when it goes by itself (`until`, `null` when it is held until emptied), and the days one is held (`days`) |
| `GET /api/v1/days` | The days that have answers, how many answers are starred, whether anything heard is kept, how many answers **Recently deleted** holds (`deleted`), and the days it holds one (`deleted_days`) |
| `GET /api/v1/heard` | What was heard and kept (**Keep what is heard**): the days, and one day's lines, `?day=YYYY-MM-DD` or the newest |
| `GET /api/v1/stats` | The counters, recent times and costs, the last error, and the settings changed from their defaults, as `./sidenote stats` shows them |
| `GET /api/v1/screen` | The latest screen as a small JPEG data URL (`url`), when it came (`ts`), and whether screens are coming now (`live`) |
| `GET /api/v1/confirms` | The problems waiting for a yes or no before they go to the agent (**Confirm before sending**), each with the seconds it has left (`timeout`). A program following the [events](#following-events) can answer them with no panel open |
| `GET /api/v1/events` | What the panels are sent, as it happens: [Following](#following-events) |

An answer kept holds what the panel draws from it: `id`, `ts`, `kind`, `text` (the whole answer as written), `transcript`
(what was heard, for a spoken problem), `turns` (the follow-ups), `check` (the code check of its examples), `thumb` (the screen it was read from), `starred`,
and the engine, model, time and cost it took.

## Changing

Each of these runs one of the panel's controls. The body is a JSON object, `{}` where the table shows none.

| Route | Body | As in the panel |
|:---|:---|:---|
| `POST /api/v1/pause` | | The pause key: no screen or speech is analyzed until resumed |
| `POST /api/v1/resume` | | The pause key again |
| `POST /api/v1/reanalyze` | | **Reanalyze**: the screen now, even unchanged (`202` with the `id` its answer takes) |
| `POST /api/v1/ask` | `{"text": "why not a heap?"}` | The question box under the latest answer (`202` with the `id` its answer takes, `409` with nothing answered yet, `429` while 8 questions are being answered) |
| `PUT /api/v1/capture` | `{"screen": false}`, `{"audio": true}`, or both | The capture card's switches |
| `PUT /api/v1/settings/{key}` | `{"value": ...}` | One control of the settings sheet. A value outside its options is refused with the panel's words (`400`) |
| `POST /api/v1/settings/reset` | | **Reset to defaults**: the values after it and what it did as `notices` (`409` when a setting could not go back) |
| `PUT /api/v1/answers/{seq}/star` | `{"starred": true}` | The star on an answer's head (`409` for an answer not kept) |
| `POST /api/v1/answers/{seq}/run` | `{"lang": "python", "code": "...", "stdin": "..."}` | **Run** under an answer's code: the program's output, its `exit` code and its time from the sandbox, a failing program included (`422` when it did not run) |
| `POST /api/v1/answers/{seq}/problem` | | **Problem text**: the latest problem written out by the local model (`409` for any other) |
| `DELETE /api/v1/answers/{seq}` | | The delete key on an answer's head: the answer leaves the panel and the history's lists and goes to **Recently deleted**, with its star and its follow-ups. `kept` says whether it is held there (`false` for an answer the history never held, which only a panel that showed it can put back), `until` when it goes by itself (`409` while the answer is still being written) |
| `POST /api/v1/answers/{seq}/restore` | | **Undo**, and **Restore** in **Recently deleted**: the answer back as it was, given as `answer` (`404` for one not held there) |
| `DELETE /api/v1/answers/deleted/{seq}` | | **Delete for good** in **Recently deleted**: that answer gone from the history file now (`404` for one not held there, an answer still shown among them: delete it first) |
| `DELETE /api/v1/answers/deleted` | | **Empty** in **Recently deleted**: every answer in it gone for good, `gone` saying how many |
| `DELETE /api/v1/answers` | | **Clear history**: every answer kept, starred ones too, what was heard, and **Recently deleted** with them |
| `POST /api/v1/confirms/{cid}` | `{"send": true}` | The confirm card: `true` sends the problem to the agent, `false` keeps it on this PC |
| `POST /api/v1/gpu/release` | | **Free GPU**: the local model leaves the GPU, and loads again for the next problem |
| `POST /api/v1/gpu/load` | | **Load to GPU**: the model on the GPU now (`202`; the engines' status says when) |
| `POST /api/v1/gpu/load/cancel` | | Stopping a load, unless a problem waits on it |
| `POST /api/v1/models/pull` | `{"model": "sidenote-gemma4:26b"}` | The local model card's download (`202`; how far it is comes as `llm_pull` events) |
| `PUT /api/v1/language/panel` | `{"lang": "en"}` | The panel's language, which the server's words follow (`409` when `SIDENOTE_LANG` holds one) |
| `PUT /api/v1/language/speech` | `{"lang": "auto"}`, `"ko"` or `"en"` | The language speech is written down in (`409` when speech is off here: `SIDENOTE_TRANSCRIBER=null` or `SIDENOTE_AUDIO=0`) |
| `POST /api/v1/capture/restart` | `{}`, or `{"quiet": true}` to wait for a moment when nothing runs | The capture program's tray: **Restart capture** |
| `POST /api/v1/capture/quit` | | The capture program's tray: **Quit**, the program alone (a server its start brought up stays) |
| `POST /api/v1/commands` | One of the panel's messages | Anything the panel sends, as it sends it: [The panel's messages](#the-panels-messages) |

A change answers with how things stand after it: `paused`, the setting's `value`, the capture's switches, the number of
starred answers, the number of answers in **Recently deleted** (`count`). A change the panel would have answered with a
note gives that note in `notices`.

A deleted answer is held in **Recently deleted** for 7 days (`SIDENOTE_DELETED_DAYS`; `0` holds it until emptied), and
leaves it earlier when the history reaches its size limit, the deleted going before any answer still shown.

## Following: events

`GET /api/v1/events` is a stream of [Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html):
each event's `data` is one message the panels are sent, as one line of JSON with its `type`, and its `id` counts them.
It starts with what a panel is told as it opens (`status`, `settings`, `capture`, `usage`, then each confirm waiting and
each answer being written, with its words so far), and goes on with each message as it goes to the panels. A comment line
comes every 15 seconds when nothing else does. A reader that connects again starts over: the opening again, and the
count from 1 (`Last-Event-ID` is not read), so it never has to piece the state together from what it missed.

```python
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8777/api/v1/events") as stream:
    for line in stream:
        if line.startswith(b"data: "):
            message = json.loads(line[6:])
            if message["type"] == "analysis_done":
                print(message["id"], message["text"].splitlines()[0])
```

| `type` | Says |
|:---|:---|
| `status` | Part of the status changed: `paused`, the engines' cards (`engines`), the speech `lang`, a newer release (`update`) |
| `settings` | The settings, all of them (`values`, and `meta` in the panel's words) |
| `capture` | The capture program: connected or not, its switches, when it last sent a screen and sound, and what the program that feeds the server said of itself as it connected (`who`: its PC's name `host`, its `system`, its release `version`, how it was `started`, the `server` address it was given, and whether its Quit `ends_server`; `since`: when that connection was made; both `null` while none is) |
| `usage` | The counters the usage card shows |
| `analysis_start` | A problem is being answered: its `id`, what set it off (`trigger`), the screen (`thumb`), what was heard (`transcript`); a follow-up says which answer it is `about` |
| `stage` | Where that answer stands: the step (`stage`), and the thinking pass's last line (`thought`) |
| `delta` | The next words of that answer (`text`) |
| `analysis_done` | The answer whole (`text`), with the `engine`, `model`, `usage`, `cost_usd` and time (`elapsed`) |
| `analysis_cancelled` | It stopped: a newer screen came, it was not sent, a person stopped it, or the answer it asked about was deleted (`reason`) |
| `error` | It failed, in words, with what to do (`hint`) |
| `check`, `verify` | The code check of an answer's examples, and the agent's check of an answer, under way and done |
| `transcript`, `utterance` | What is being heard now, and a sentence closed |
| `agent_confirm`, `agent_confirm_done` | A problem waits for a yes or no before it goes to the agent ([`POST /api/v1/confirms/{cid}`](#changing)), and it no longer does |
| `notice` | A note the panel shows (`level`, `text`) |
| `star`, `history_cleared` | An answer starred or unstarred (`n`: how many are now), and the history cleared |
| `answer_deleted`, `answer_restored` | An answer deleted (`kept`, `until`) and one put back (`answer`: the answer as the history gives it), each with how many **Recently deleted** holds now (`n`) and whether there is an answer to ask about (`can_ask`) |
| `deleted_cleared` | Answers gone from **Recently deleted** for good: one (`id`) or all of them (`id` is `null`), how many went (`gone`) and how many are left (`n`) |
| `gpu`, `llm_pull` | The GPU's reading, and a model download's progress |
| `lagged` | This stream fell 2,000 messages behind and lost the oldest (`lost`): read `GET /api/v1/status` again |

The answer to a question asked with [`POST /api/v1/ask`](#changing), or to a screen after
[`POST /api/v1/reanalyze`](#changing), comes this way: an `analysis_start`, its `delta`s, then `analysis_done` or
`analysis_cancelled` or `error` for the same `id`, the one their `202` named. Once done it is kept, and
`GET /api/v1/answers/{seq}` gives it, `{seq}` being that `id`. A Reanalyze with no screen and nothing heard to run on
starts none, and a `notice` says so instead.

## The panel's messages

The panel talks to the server over a socket, and each message it sends has a route here. `POST /api/v1/commands` takes
any of them as the panel sends it, and answers with what the server sent back to the panel that sent it (`replies`).

| The panel's message | Its route |
|:---|:---|
| `pause`, `resume` | `POST /api/v1/pause`, `POST /api/v1/resume` |
| `reanalyze` | `POST /api/v1/reanalyze` |
| `ask` | `POST /api/v1/ask` |
| `capture_set` | `PUT /api/v1/capture` |
| `capture_restart`, `capture_quit` | `POST /api/v1/capture/restart`, `POST /api/v1/capture/quit` |
| `setting` | `PUT /api/v1/settings/{key}` |
| `settings_reset` | `POST /api/v1/settings/reset` |
| `star` | `PUT /api/v1/answers/{seq}/star` |
| `run` | `POST /api/v1/answers/{seq}/run` |
| `problem_text` | `POST /api/v1/answers/{seq}/problem` |
| `answer_delete`, `answer_restore` | `DELETE /api/v1/answers/{seq}`, `POST /api/v1/answers/{seq}/restore` |
| `answer_purge`, `deleted_clear` | `DELETE /api/v1/answers/deleted/{seq}`, `DELETE /api/v1/answers/deleted` |
| `history_clear` | `DELETE /api/v1/answers` |
| `agent_confirm_reply` | `POST /api/v1/confirms/{cid}` |
| `thumb` | `GET /api/v1/screen` |
| `gpu_release`, `gpu_load`, `gpu_load_cancel` | `POST /api/v1/gpu/release`, `POST /api/v1/gpu/load`, `POST /api/v1/gpu/load/cancel` |
| `llm_pull` | `POST /api/v1/models/pull` |
| `ui_lang` | `PUT /api/v1/language/panel` |
| `set_lang` | `PUT /api/v1/language/speech` |

```sh
curl -s -X POST http://127.0.0.1:8777/api/v1/commands -H 'Content-Type: application/json' -d '{"type": "thumb"}'
```

A message refused through `/commands` is answered `200` with the refusal among its `replies`, a notice of level `warn`
(`bad` when it failed), as the panel is told: `set_lang` where speech is off here, for one, where its own route answers `409`.

The tests hold the two together: a message the panel sends with no route here, or a route missing from this page, fails
them (`tests/api_check.py`).

## Versions

`/api/v1` keeps what it has. What is added to it (a route, a field, an event) leaves a program written for it working; a
change that would not goes to `/api/v2`, beside it, for a release before `/api/v1` goes. The server's own version is in
`GET /api/v1` (`version`) and `/health`.
