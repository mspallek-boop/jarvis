#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
test_output=$(mktemp -d /tmp/jarvis-clipboard-tests.XXXXXX)
xcrun swiftc -module-cache-path "$test_output/ModuleCache" -parse-as-library \
    Sources/Services/PlatformImage.swift Tests/PlatformImageTests.swift \
    -o "$test_output/PlatformImageTests"
"$test_output/PlatformImageTests"
