PS2 Mod Manager — User Catalogue
=================================

Drop custom JSON files into this folder to add your own catalogue entries.
Each JSON file must contain a top-level array of entry objects.

The "type" field controls which tab an entry appears in:
  texture_pack  — Texture Packs tab
  pnach         — PNACH Patches tab
  save_file     — Save Files tab
  cheat         — Cheats tab
  cover_art     — Cover Art tab

Required fields (every entry must have all of these):
  id            Unique identifier string (e.g. "my-pack-sly2-hd")
  name          Display name
  description   Short description shown in the UI
  author        Creator's name
  url           Link to the mod page / download page
  source        Source label (e.g. "GameFront", "Personal")
  game          Full game title (e.g. "Sly 2: Band of Thieves")
  game_serial   PS2 disc serial (e.g. "SCUS-97264")
  type          Mod type (see list above)

Optional fields (all have sensible defaults if omitted):
  context             ""
  author_url          ""
  is_hub              false
  nsfw                false
  thumbnail_url       ""
  tags                []
  download_action     ""
  direct_download_url ""
  upscale_tech        ""
  is_free             true
  requires_account    false
  is_complete         true
  size_label          ""   (e.g. "~250 MB")

Example entry:
[
  {
    "id": "my-pack-sly2-hd",
    "name": "Sly 2 HD Textures",
    "description": "Hand-crafted HD texture replacement for Sly 2.",
    "author": "YourName",
    "url": "https://example.com/sly2-hd",
    "source": "Personal",
    "game": "Sly 2: Band of Thieves",
    "game_serial": "SCUS-97264",
    "type": "texture_pack",
    "size_label": "~250 MB"
  }
]

Notes:
- IDs must be unique across all catalogue files (including built-in ones).
- Files with JSON parse errors are skipped (a warning is logged).
- Restart the application after adding or editing files here.
