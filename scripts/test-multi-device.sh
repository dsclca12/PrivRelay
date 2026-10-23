#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

printf '%s\n' '== Go backend: race-enabled full suite (includes synthetic two-device E2EE/WebSocket flow) =='
(cd "$repo_root/server" && go test -race ./... -count=1)

printf '%s\n' '== Flutter: static analysis =='
(cd "$repo_root/android_client" && flutter analyze)

printf '%s\n' '== Flutter: unit and widget tests =='
(cd "$repo_root/android_client" && flutter test)

printf '%s\n' '== Android: native unit tests =='
(cd "$repo_root/android_client/android" && ./gradlew :app:testDevDebugUnitTest)
