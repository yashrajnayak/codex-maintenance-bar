// swift-tools-version: 6.0

import PackageDescription

let package = Package(
  name: "CodexMaintenanceBar",
  platforms: [
    .macOS(.v14)
  ],
  products: [
    .executable(name: "CodexMaintenanceBar", targets: ["CodexMaintenanceBar"])
  ],
  targets: [
    .executableTarget(
      name: "CodexMaintenanceBar",
      resources: [
        .copy("Resources")
      ]
    )
  ]
)
