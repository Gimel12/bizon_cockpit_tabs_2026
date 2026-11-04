#!/bin/sh
# Add the BIZON artwork to GNOME's wallpaper selector without selecting it.
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run this installer as an administrator.' >&2
    exit 1
fi
wallpaper_source=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -d -o root -g root -m 755 /usr/local/share/backgrounds/bizon
install -d -o root -g root -m 755 /usr/share/gnome-background-properties
install -o root -g root -m 644 "$wallpaper_source/bizon-blue-4k.png" "$wallpaper_source/bizon-blue-1080p.png" /usr/local/share/backgrounds/bizon/
install -o root -g root -m 644 "$wallpaper_source/bizon-wallpapers.xml" /usr/share/gnome-background-properties/bizon-wallpapers.xml
printf '%s\n' 'BIZON Blue is available in Settings > Appearance. The current background has not changed.'
