// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "LinkBar",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "LinkBar",
            path: "Sources/LinkBar",
            resources: [.process("Resources")]
        )
    ]
)
