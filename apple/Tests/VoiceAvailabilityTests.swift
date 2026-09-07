import Foundation

@main
struct VoiceAvailabilityTests {
    static func main() throws {
        let eleven = JarvisAPIClient.VoicesResponse(
            provider: "ElevenLabs",
            voices: [voice(id: "legacy-eleven")],
            selected: "legacy-eleven"
        )
        precondition(eleven.isElevenLabs)
        precondition(eleven.appSelectableVoices.isEmpty)

        let local = JarvisAPIClient.VoicesResponse(
            provider: "local",
            voices: [voice(id: "mac-voice")],
            selected: "mac-voice"
        )
        precondition(!local.isElevenLabs)
        precondition(local.appSelectableVoices.map(\.id) == ["mac-voice"])

        print("Voice availability: ElevenLabs hidden, non-ElevenLabs voices retained")
    }

    private static func voice(id: String) -> JarvisAPIClient.BridgeVoice {
        JarvisAPIClient.BridgeVoice(
            id: id,
            name: "Test voice",
            accent: "",
            gender: "",
            description: ""
        )
    }
}
