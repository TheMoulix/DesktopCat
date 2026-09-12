#!/usr/bin/env bash
# DesktopCat - Linux Setup Script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================================"
echo "🐱 Setting up DesktopCat for Linux..."
echo "========================================================"

chmod +x start.sh stop.sh setup.sh cat_overlay.py cat_overlay.pyw 2>/dev/null || true

# Generate app_icon.png from app_icon.ico if needed
python3 -c "
import os
from PIL import Image
if not os.path.exists('app_icon.png') and os.path.exists('app_icon.ico'):
    try:
        im = Image.open('app_icon.ico')
        im.save('app_icon.png')
        print('Generated app_icon.png')
    except Exception as e:
        print('Could not generate PNG icon:', e)
"

# Create Desktop entry
cat > "$SCRIPT_DIR/DesktopCat.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=DesktopCat
Comment=Always-on-top animated desktop companion
Exec=$SCRIPT_DIR/start.sh
Icon=$SCRIPT_DIR/app_icon.png
Terminal=false
Categories=Utility;Amusement;
EOF
chmod +x "$SCRIPT_DIR/DesktopCat.desktop"

# Check dependencies
echo "Checking dependencies..."
python3 -c "
import sys
missing = []
for mod in ['PIL', 'gi', 'cairo']:
    try:
        __import__(mod)
    except ImportError:
        missing.append(mod)

if missing:
    print('NOTE: The following Python modules are missing:', ', '.join(missing))
    print('Install them using your package manager (e.g. python3-pillow, python3-gobject, python3-cairo).')
else:
    print('All required dependencies (PIL, PyGObject, Cairo) are installed!')
"

echo ""
echo "[SUCCESS] DesktopCat is ready!"
echo "• Run ./start.sh to launch the cat"
echo "• Run ./stop.sh to close the cat"
