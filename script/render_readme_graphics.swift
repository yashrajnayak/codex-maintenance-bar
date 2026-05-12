#!/usr/bin/env swift

import AppKit

let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
let output = root.appendingPathComponent("assets/readme/architecture-diagram.png")
let size = NSSize(width: 1600, height: 900)
let image = NSImage(size: size)

let ink = NSColor(calibratedRed: 0.09, green: 0.12, blue: 0.16, alpha: 1)
let mutedInk = NSColor(calibratedRed: 0.23, green: 0.28, blue: 0.34, alpha: 0.82)
let lineColor = NSColor(calibratedRed: 0.18, green: 0.23, blue: 0.30, alpha: 0.58)

struct Box {
  let title: String
  let subtitle: String
  let rect: NSRect
  let fill: NSColor
}

func drawText(
  _ text: String,
  in rect: NSRect,
  size: CGFloat,
  weight: NSFont.Weight,
  color: NSColor = ink,
  alignment: NSTextAlignment = .center
) {
  let paragraph = NSMutableParagraphStyle()
  paragraph.alignment = alignment
  paragraph.lineBreakMode = .byWordWrapping

  let attributes: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: size, weight: weight),
    .foregroundColor: color,
    .paragraphStyle: paragraph
  ]

  NSString(string: text).draw(in: rect, withAttributes: attributes)
}

func drawRoundedBox(_ box: Box) {
  NSGraphicsContext.saveGraphicsState()
  let shadow = NSShadow()
  shadow.shadowColor = NSColor.black.withAlphaComponent(0.12)
  shadow.shadowBlurRadius = 18
  shadow.shadowOffset = NSSize(width: 0, height: -8)
  shadow.set()

  let path = NSBezierPath(roundedRect: box.rect, xRadius: 18, yRadius: 18)
  box.fill.setFill()
  path.fill()
  NSGraphicsContext.restoreGraphicsState()

  NSColor.white.withAlphaComponent(0.9).setStroke()
  path.lineWidth = 2
  path.stroke()

  drawText(
    box.title,
    in: NSRect(x: box.rect.minX + 22, y: box.rect.midY + 10, width: box.rect.width - 44, height: 34),
    size: 23,
    weight: .semibold
  )
  drawText(
    box.subtitle,
    in: NSRect(x: box.rect.minX + 28, y: box.rect.midY - 58, width: box.rect.width - 56, height: 52),
    size: 17,
    weight: .regular,
    color: mutedInk
  )
}

func drawArrow(from start: NSPoint, to end: NSPoint) {
  let path = NSBezierPath()
  path.move(to: start)
  path.line(to: end)
  lineColor.setStroke()
  path.lineWidth = 5
  path.lineCapStyle = .round
  path.stroke()

  let angle = atan2(end.y - start.y, end.x - start.x)
  let arrowLength: CGFloat = 20
  let spread: CGFloat = .pi / 7
  let p1 = NSPoint(x: end.x - arrowLength * cos(angle - spread), y: end.y - arrowLength * sin(angle - spread))
  let p2 = NSPoint(x: end.x - arrowLength * cos(angle + spread), y: end.y - arrowLength * sin(angle + spread))

  let head = NSBezierPath()
  head.move(to: end)
  head.line(to: p1)
  head.line(to: p2)
  head.close()
  lineColor.setFill()
  head.fill()
}

image.lockFocus()

let bounds = NSRect(origin: .zero, size: size)
NSColor(calibratedRed: 0.96, green: 0.97, blue: 0.95, alpha: 1).setFill()
bounds.fill()

let header = NSBezierPath(rect: NSRect(x: 0, y: 650, width: size.width, height: 250))
NSColor(calibratedRed: 0.79, green: 0.90, blue: 0.96, alpha: 1).setFill()
header.fill()

drawText(
  "codex-powertoyz",
  in: NSRect(x: 120, y: 772, width: 1360, height: 56),
  size: 46,
  weight: .bold
)
drawText(
  "Menu bar controls for awake sessions, Codex maintenance, backups, reports, and scheduled cleanup",
  in: NSRect(x: 190, y: 724, width: 1220, height: 38),
  size: 22,
  weight: .regular,
  color: mutedInk
)

let topBoxes = [
  Box(
    title: "Menu Bar",
    subtitle: "One local control surface",
    rect: NSRect(x: 80, y: 470, width: 270, height: 150),
    fill: NSColor(calibratedRed: 1.00, green: 0.98, blue: 0.90, alpha: 1)
  ),
  Box(
    title: "Awake Control",
    subtitle: "Codex detection plus caffeinate",
    rect: NSRect(x: 420, y: 470, width: 280, height: 150),
    fill: NSColor(calibratedRed: 0.90, green: 0.96, blue: 1.00, alpha: 1)
  ),
  Box(
    title: "Maintenance",
    subtitle: "Audit, cleanup, and restore",
    rect: NSRect(x: 770, y: 470, width: 280, height: 150),
    fill: NSColor(calibratedRed: 0.92, green: 0.98, blue: 0.91, alpha: 1)
  ),
  Box(
    title: "Schedule",
    subtitle: "Weekly LaunchAgent",
    rect: NSRect(x: 1120, y: 470, width: 280, height: 150),
    fill: NSColor(calibratedRed: 0.98, green: 0.93, blue: 0.99, alpha: 1)
  )
]

let bottomBoxes = [
  Box(
    title: "Codex State",
    subtitle: "Sessions, logs, config, workspaces",
    rect: NSRect(x: 250, y: 230, width: 300, height: 150),
    fill: NSColor(calibratedRed: 0.98, green: 0.95, blue: 0.88, alpha: 1)
  ),
  Box(
    title: "Backups",
    subtitle: "State DBs, transcripts, manifests",
    rect: NSRect(x: 650, y: 230, width: 300, height: 150),
    fill: NSColor(calibratedRed: 0.91, green: 0.96, blue: 1.00, alpha: 1)
  ),
  Box(
    title: "Reports",
    subtitle: "Markdown summaries and next steps",
    rect: NSRect(x: 1050, y: 230, width: 300, height: 150),
    fill: NSColor(calibratedRed: 0.94, green: 0.98, blue: 0.92, alpha: 1)
  )
]

for box in topBoxes + bottomBoxes {
  drawRoundedBox(box)
}

drawArrow(from: NSPoint(x: 350, y: 545), to: NSPoint(x: 420, y: 545))
drawArrow(from: NSPoint(x: 700, y: 545), to: NSPoint(x: 770, y: 545))
drawArrow(from: NSPoint(x: 1050, y: 545), to: NSPoint(x: 1120, y: 545))
drawArrow(from: NSPoint(x: 910, y: 470), to: NSPoint(x: 480, y: 380))
drawArrow(from: NSPoint(x: 910, y: 470), to: NSPoint(x: 800, y: 380))
drawArrow(from: NSPoint(x: 910, y: 470), to: NSPoint(x: 1180, y: 380))

let noteRect = NSRect(x: 250, y: 88, width: 1100, height: 88)
let notePath = NSBezierPath(roundedRect: noteRect, xRadius: 16, yRadius: 16)
NSColor.white.withAlphaComponent(0.76).setFill()
notePath.fill()
NSColor(calibratedRed: 0.20, green: 0.27, blue: 0.34, alpha: 0.12).setStroke()
notePath.lineWidth = 2
notePath.stroke()

drawText(
  "Read-only audits come first. Cleanup actions write reports, keep manifests, and back up local Codex state before destructive changes.",
  in: NSRect(x: noteRect.minX + 62, y: noteRect.minY + 25, width: noteRect.width - 124, height: 42),
  size: 18,
  weight: .medium,
  color: mutedInk
)

image.unlockFocus()

guard
  let tiff = image.tiffRepresentation,
  let bitmap = NSBitmapImageRep(data: tiff),
  let png = bitmap.representation(using: .png, properties: [:])
else {
  fatalError("Could not render README architecture diagram")
}

try FileManager.default.createDirectory(
  at: output.deletingLastPathComponent(),
  withIntermediateDirectories: true
)
try png.write(to: output)
