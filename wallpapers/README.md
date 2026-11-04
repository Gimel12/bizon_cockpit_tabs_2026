# BIZON Blue desktop wallpaper

Optional OS desktop artwork based on the Cockpit blue background, with a compact white BIZON wordmark at the bottom right. The wordmark follows the existing BIZON OS wallpaper reference, including the power symbol in the O.

- `bizon-blue-4k.png`: 3840 × 2160, 16:9.
- `bizon-blue-1080p.png`: 1920 × 1080, 16:9.

Run `sudo ./wallpapers/install.sh` from a reviewed checkout. This registers one **BIZON Blue** choice in GNOME Appearance, using the 4K file for both light and dark mode; GNOME scales it for a Full HD screen. It leaves all current background settings and existing wallpaper files unchanged. Both images are installed in `/usr/local/share/backgrounds/bizon/`. The files can also be selected manually in other desktops. These OS assets are separate from signed Cockpit tab archives and are included when the OS is cloned after installation.

The background and logo composition were edited with the built-in image generation tool using the existing wallpaper as the logo reference. The generated 1672 × 941 artwork was resampled into the exact display-size exports. These are resolution-matched exports, not a claim that the image was generated natively at 4K. Logo placement is inset from the right/bottom edge and remains clear at both target sizes.
