# Transitions

`impromptu composite` passes the scene `transition` name straight to FFmpeg's
`xfade` filter (plus `acrossfade` for audio). There are **58 native**
transitions (indices 0-57, verified with `ffmpeg -h filter=xfade`), plus the
impromptu-only `none` alias (a 0.01s fade = effectively an instant cut).

Fades: `fade` `fadeblack` `fadewhite` `fadefast` `fadeslow` `fadegrays`
Slides: `slideleft` `slideright` `slideup` `slidedown`
        `smoothleft` `smoothright` `smoothup` `smoothdown`
Wipes: `wipeleft` `wiperight` `wipeup` `wipedown`
       `wipetl` `wipetr` `wipebl` `wipebr`
Reveals/covers: `revealleft` `revealright` `revealup` `revealdown`
                `coverleft` `coverright` `coverup` `coverdown`
Open/close: `circleopen` `circleclose` `vertopen` `vertclose`
            `horzopen` `horzclose`
Crop: `circlecrop` `rectcrop`
Diagonal: `diagtl` `diagtr` `diagbl` `diagbr`
Slices: `hlslice` `hrslice` `vuslice` `vdslice`
Winds: `hlwind` `hrwind` `vuwind` `vdwind`
Other: `dissolve` `pixelize` `radial` `distance` `hblur`
       `squeezeh` `squeezev` `zoomin` `none` (alias)

## Effects

Per-scene presenter `effects` and `graphic_effects`:

- `zoompan` (Ken Burns) — note: per-frame zoompan on full-HD presenter
  footage is slow; prefer it on graphics, or leave presenter effects off.
- `chromakey` (green screen, presenter only)
- `rotate` (degrees), `hflip`, `vflip` (presenter only)

Example:

```json
{"mode": "corner", "graphic": 0, "start_sec": 10.0, "end_sec": 28.0,
 "transition": "slideleft", "transition_duration": 0.5,
 "pip_position": "bottom-right", "pip_scale": 0.25,
 "graphic_effects": [{"type": "zoompan", "z": "1.15"}]}
```

PiP positions: `bottom-right` `bottom-left` `top-right` `top-left`
(30px inset, rounded corners, subtle shadow).
