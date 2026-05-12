// swift-tools-version: 6.0

import PackageDescription

let package = Package(
  name: "codex-powertoyz",
  platforms: [
    .macOS(.v14)
  ],
  products: [
    .executable(name: "codex-powertoyz", targets: ["CodexPowertoyz"])
  ],
  targets: [
    .executableTarget(
      name: "CodexPowertoyz",
      resources: [
        .copy("Resources")
      ]
    )
  ]
)
