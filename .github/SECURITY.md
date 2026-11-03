# Security

## Reporting a vulnerability

Please report a security problem privately: on GitHub, open the repository's **Security** tab and choose **Report a
vulnerability**. Do not open a public issue for it.

Say what an attacker can do, how to reproduce it, and which version you ran (a release tag or a commit). The
maintainer will reply, agree on a fix with you, and publish an advisory with the fixed release, crediting you unless
you ask not to be named.

The latest release and `main` get security fixes.

## What matters most

Sidenote reads the screen and the speaker sound, runs code a model wrote, and uses a cloud agent's login. These are
the problems to report:

- a web page, another program or another container that can talk to the server, the panel or the code runner;
- code in an answer that gets out of the runner's sandbox: its network, its user, its limits;
- a screen, a crop or speech that leaves the PC in a way the user guide does not describe
  ([Security and privacy](docs/README.md#14-security-and-privacy));
- an agent login or an API key that can be read from outside the server;
- a frame, an answer or a search result that makes the panel run script.

The server listens on `127.0.0.1` only. Publishing its port to a network on purpose is outside what it is built to
protect: the panel has no login.
