#!/usr/bin/env bash
# MIDI Studio - Linux uninstaller (undoes install-linux.sh).
# Usage:  bash uninstall-linux.sh [--yes]
# --yes answers the questions with their standard answers (remove downloaded
# LilyPond: yes; remove your saved settings: no).
set -u
yes_all=0
[ "${1:-}" = "--yes" ] || [ "${1:-}" = "-y" ] && yes_all=1

say() { printf '%s\n' "$*"; }
ask() {   # ask "question" default(y|n) -> 0 for yes
    local def="$2" r hint="[Y/n]"
    [ "$def" = n ] && hint="[y/N]"
    if [ "$yes_all" = 1 ] || [ ! -t 0 ]; then [ "$def" = y ]; return; fi
    read -r -p "$1 $hint " r
    case "$r" in y|Y|yes|YES|Yes) return 0 ;; n|N|no|NO|No) return 1 ;; *) [ "$def" = y ] ;; esac
}

data="${XDG_DATA_HOME:-$HOME/.local/share}"
rm -f "$HOME/Applications/MIDI-Studio-x86_64.AppImage" && say "Removed the program from ~/Applications (if it was there)."
rm -f "$data/applications/midi-studio.desktop" && say "Removed the application-menu entry (if there was one)."
rm -f "$data/midi-studio/midi-studio.png"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$data/applications" >/dev/null 2>&1

ly="$data/midi-studio/ly"
if [ -d "$ly" ]; then
    say ""
    say "MIDI Studio downloaded its own copy of LilyPond (the program that prints scores) into:"
    say "    $ly"
    if ask "Remove it too? (A LilyPond you installed yourself is never touched.)" y; then
        rm -rf "$ly" && say "Removed the downloaded LilyPond."
    else
        say "Kept the downloaded LilyPond."
    fi
fi
rmdir "$data/midi-studio" 2>/dev/null

cfg="$HOME/.midistudio_settings.json"
if [ -f "$cfg" ]; then
    say ""
    if ask "Also remove your saved MIDI Studio settings ($cfg)?" n; then
        rm -f "$cfg" && say "Removed your settings."
    else
        say "Kept your settings."
    fi
fi
say "Done."
