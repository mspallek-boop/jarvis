#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
test_output="$PWD/LocalData/inline-image-validation/swift-tests"
mkdir -p "$test_output"
xcrun swiftc -O -module-cache-path "$test_output/ModuleCache" -parse-as-library \
    apple/Sources/Models/ChatMessage.swift apple/Sources/Services/JarvisAPIClient.swift \
    apple/Sources/Services/PlatformImage.swift apple/Sources/Services/SpeechText.swift \
    apple/Tests/InlineImageTests.swift -o "$test_output/InlineImageTests"
"$test_output/InlineImageTests"
