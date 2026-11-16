-- Omarchy Lua configuration: add to ~/.config/hypr/bindings.lua.
-- First inspect: omarchy menu keybindings --print
-- These replace Super+E and the two stock Nautilus shortcuts.
hl.unbind("SUPER + E")
hl.unbind("SUPER + SHIFT + F")
hl.unbind("SUPER + ALT + SHIFT + F")
o.bind("SUPER + E", "File manager", { launch = "nemo" })
o.bind("SUPER + SHIFT + F", "File manager", { launch = "nemo" })
o.bind("SUPER + ALT + SHIFT + F", "File manager (cwd)", {
    launch = 'nemo "$(omarchy-cmd-terminal-cwd)"',
})
-- Validate after saving:
-- hyprctl reload
-- hyprctl configerrors
