#!/usr/bin/env bash
# MIDI Studio - Linux installer (per user, no administrator password).
# Usage:  bash install-linux.sh [path-to-MIDI-Studio-x86_64.AppImage]
# It copies the AppImage to ~/Applications and adds MIDI Studio to your
# application menu.  To remove it again: bash uninstall-linux.sh
set -u

yes_all=0
img=""
for a in "$@"; do
    case "$a" in
        --yes|-y) yes_all=1 ;;
        *) img="$a" ;;
    esac
done

say() { printf '%s\n' "$*"; }

ask_yes() {   # ask_yes "question" -> 0 for yes (default yes)
    [ "$yes_all" = 1 ] && return 0
    [ -t 0 ] || return 0
    local r
    read -r -p "$1 [Y/n] " r
    case "$r" in n|N|no|NO|No) return 1 ;; *) return 0 ;; esac
}

if [ "$(uname -m)" != "x86_64" ]; then
    say "This download is for 64-bit Intel/AMD computers (x86_64); this one reports $(uname -m)."
    exit 1
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -z "$img" ]; then
    for d in "$here" "$PWD" "$HOME/Downloads"; do
        found="$(ls -1t "$d"/MIDI-Studio*.AppImage 2>/dev/null | head -n1)"
        if [ -n "$found" ]; then img="$found"; break; fi
    done
fi
if [ -z "$img" ] || [ ! -f "$img" ]; then
    say "I could not find MIDI-Studio-x86_64.AppImage."
    say "Download it first (https://github.com/winthrom/midi-studio/releases/latest),"
    say "then run:  bash install-linux.sh /path/to/MIDI-Studio-x86_64.AppImage"
    exit 1
fi

apps="$HOME/Applications"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
dest="$apps/MIDI-Studio-x86_64.AppImage"
mkdir -p "$apps" || exit 1
if [ "$(readlink -f "$img")" != "$(readlink -f "$dest")" ]; then
    cp -f "$img" "$dest" || { say "Could not copy the program to $apps"; exit 1; }
fi
chmod +x "$dest"
say "Program copied to: $dest"

# Newer Ubuntu/Kubuntu need a small library (FUSE 2) to start an AppImage normally.
# Without it the program still works: it unpacks itself on each start (a little slower).
exec_prefix=""
if ! ldconfig -p 2>/dev/null | grep -q 'libfuse\.so\.2'; then
    exec_prefix="env APPIMAGE_EXTRACT_AND_RUN=1 "
    say ""
    say "Note: the small library 'libfuse2' is not installed on this computer."
    say "The program will still start, but a little slower (it unpacks itself each time)."
    say "For a faster start, install it once with your package manager, for example:"
    say "    sudo apt install libfuse2        (Ubuntu 24.04 and newer: libfuse2t64)"
fi

if ask_yes "Add MIDI Studio to your application menu?"; then
    icon=""
    tmp="$(mktemp -d)"
    ( cd "$tmp" && "$dest" --appimage-extract '*.png' >/dev/null 2>&1 )
    pic="$(ls -1 "$tmp"/squashfs-root/midi-studio.png "$tmp"/squashfs-root/*.png 2>/dev/null | head -n1)"
    if [ -n "$pic" ]; then
        mkdir -p "$data/midi-studio"
        cp -f "$pic" "$data/midi-studio/midi-studio.png" && icon="$data/midi-studio/midi-studio.png"
    fi
    rm -rf "$tmp"
    mkdir -p "$data/applications"
    cat > "$data/applications/midi-studio.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=MIDI Studio
Comment=MIDI file editing and music notation
Exec=${exec_prefix}"$dest"
Icon=${icon:-audio-x-generic}
Categories=AudioVideo;Audio;Midi;Music;
Terminal=false
DESK
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$data/applications" >/dev/null 2>&1
    say "MIDI Studio was added to your application menu (look under Sound & Video, or search for 'MIDI Studio')."
    say "If it does not show up at once, log out and in again."
else
    say "Not added to the menu. You can start it by double-clicking $dest"
fi

say ""
say "Printing scores needs LilyPond. Install it with your package manager if you do not have it:"
say "    sudo apt install lilypond        (Arch/EndeavourOS: sudo pacman -S lilypond)"
say "Done."
