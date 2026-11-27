#!/usr/bin/env bash
exec bash "$(dirname "$0")/../_fixture/build.sh" app 388-briefed outbox-mail
