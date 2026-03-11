# VegaClick v16

VegaClick v16 is a standalone, lightweight, high-performance auto-clicker/GUI overlay designed to interact with IDE chat interfaces (such as Cursor, Windsurf, or VS Code). It operates through a modern two-part architecture consisting of a Deep Scanner and a Fast Clicker.

This repository serves as the dedicated, standalone home for VegaClick.

## Features

- **Deep Scanner Engine**: Recursively traverses the entire DOM tree (including Shadow DOMs and iframes) to find specifically targeted elements.
- **Fast Clicker**: Rapidly consumes the scanner's payload, applies deduping and danger-checks, and initiates high-speed clicks with visual feedback (ripple effect) overlaid on top of the UI.
- **Machine Learning Integration**: Built-in logic scores interactions to prioritize UI elements avoiding bad click patterns for future interactions.
- **Agentic Bridge API**: Offers a local HTTP service (`127.0.0.1:4242`) for automated scripts to inject context and read the DOM dynamically.
- **Minimal Overlay UI**: A draggable, translucent "pill" overlay that provides instant control (Play/Pause/Stop) and live click stats.

## Setup Instructions

### Prerequisites

- Python (3.10+)
- Windows OS (Required for overlay mechanics, process footprint discovery, and taskkill cleanup routines)
- `ws` / `websockets` Python library

### Installation

1. Install the required dependenceies using `pip`:
   ```bash
   pip install websockets asyncio urllib3
   ```
   *(Note: The built-in tkinter, json, queue, os, subprocess modules are already included with Python).*

2. Launch VegaClick:
   Run the included batch script to launch the overlay:
   ```cmd
   launch.bat
   ```
   Alternatively, run it directly without a command window via:
   ```cmd
   pythonw vegaclick.py
   ```

## Usage

Once launched, the VegaClick interface will appear as a pill-shaped overlay on your screen. You can grab and drag this pill around.

- **▶ (Play)**: Starts or resumes the deep scanner and clicker.
- **⏸ (Pause)**: Halts the scanning/clicking temporarily.
- **■ (Stop)**: Stops the process and idles.
- **◎ (Overlay Toggle)**: Enables or disables the visual "ripple" effects injected around clicked buttons.

## Important Note

VegaClick employs CDP (Chrome DevTools Protocol) to evaluate JavaScript on the page dynamically. To ensure it functions correctly with your IDE's web-based chat panels, ensure that Chrome/VSC/Electron remote debugging is active and exposing an open port in the `9222-9242` range.
