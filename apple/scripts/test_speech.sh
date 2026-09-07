#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."
test_output=$(mktemp -d /tmp/jarvis-speech-tests.XXXXXX)

# These suites follow the repository's standalone @main test convention.
for suite in SpeechText AnswerText BargeInDetector; do
    xcrun swiftc -module-cache-path "$test_output/ModuleCache" -parse-as-library "Sources/Services/${suite}.swift" \
        "Tests/${suite}Tests.swift" -o "$test_output/${suite}Tests"
    "$test_output/${suite}Tests"
done
xcrun swiftc -module-cache-path "$test_output/ModuleCache" -parse-as-library Sources/Services/SpeechText.swift \
    Sources/Services/SpeechSentenceBuffer.swift Tests/SpeechSentenceBufferTests.swift \
    -o "$test_output/SpeechSentenceBufferTests"
"$test_output/SpeechSentenceBufferTests"
xcrun swiftc -module-cache-path "$test_output/ModuleCache" -parse-as-library WatchApp/WatchSentenceQueue.swift \
    Tests/WatchSentenceQueueTests.swift -o "$test_output/WatchSentenceQueueTests"
"$test_output/WatchSentenceQueueTests"

xcrun swiftc -module-cache-path "$test_output/ModuleCache" -parse-as-library Sources/Services/SpeechPlaybackSpeed.swift \
    Sources/Services/NeuralSpeechPlayer.swift Sources/Services/SpeechText.swift \
    Sources/Services/JarvisAPIClient.swift Sources/Models/ChatMessage.swift \
    Tests/SpeechPlaybackSpeedTests.swift -o "$test_output/SpeechPlaybackSpeedTests"
"$test_output/SpeechPlaybackSpeedTests" "$@"

xcrun swiftc -module-cache-path "$test_output/ModuleCache" -parse-as-library \
    Sources/Services/JarvisAPIClient.swift Sources/Models/ChatMessage.swift \
    Tests/VoiceAvailabilityTests.swift -o "$test_output/VoiceAvailabilityTests"
"$test_output/VoiceAvailabilityTests"

echo "Test executables: $test_output"
