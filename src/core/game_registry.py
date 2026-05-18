"""PS2 game serial / ID recognition utilities.

PS2 game serials follow this pattern:
    <REGION_CODE>-<5-digit number>

Region codes (retail discs):
    SLUS / SCUS — North America
    SLES / SCES — Europe (PAL)
    SLPS / SCPS — Japan
    SLKA / SCKA — Korea
    SLAJ / SCAJ — Asia
    SLPM / SCPM — Japan (Platinum / budget re-release)
    SLEH / SCEH — Europe (others)
    PBPX          — Disc ID variant

Region codes (demo / promo discs):
    SCED / SLED — Europe demo
    SCPD / SLPD — Japan demo / promo
    SCZS         — European special
    SCCS / SLCS  — Chinese / Taiwan

Common filename patterns that embed the serial:
    SLUS_20062.pnach            PNACH (underscores instead of dash)
    SLUS-20062.png              Cover art
    SLUS20062.jpg               Fused (no separator)

PNACH filenames use the **game CRC** (8 hex digits), *not* the serial, so
we can only detect serial if the filename itself contains SLUS/SCUS/etc.

PCSX2 texture replacement folder structure:
    textures/<SERIAL>/replacements/   e.g. textures/SLUS-20062/replacements/

Usage::

    from src.core.game_registry import (
        detect_game_serial, detect_serial_from_path,
        serial_to_display, title_to_serials, SERIAL_PREFIXES,
    )

    serial = detect_game_serial("SLUS-20062.pnach")     # -> "SLUS-20062"
    serial = detect_game_serial("SLUS_20062.png")       # -> "SLUS-20062"
    serial = detect_game_serial("SLUS20062_HD.zip")     # -> "SLUS-20062"
    serial = detect_serial_from_path(                   # -> "SLUS-20062"
        "/textures/SLUS-20062/replacements/pack.zip")
    display = serial_to_display("SLUS-20183")           # -> "SLUS-20183 — Spyro: Enter the Dragonfly"
    hits   = title_to_serials("kingdom hearts")         # -> [("SLUS-20370", "Kingdom Hearts"), ...]
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# All valid PS2 serial prefix strings (exported for UI validation)
# ---------------------------------------------------------------------------

#: Tuple of every known valid 4-letter PS2 serial prefix (upper-case).
SERIAL_PREFIXES: Tuple[str, ...] = (
    # Retail — North America
    "SLUS", "SCUS",
    # Retail — Europe / PAL
    "SLES", "SCES", "SLEH", "SCEH",
    # Retail — Japan
    "SLPS", "SCPS", "SLPM", "SCPM",
    # Retail — Korea
    "SLKA", "SCKA",
    # Retail — Asia
    "SLAJ", "SCAJ",
    # Demo / promo — Europe
    "SCED", "SLED",
    # Demo / promo — Japan
    "SCPD", "SLPD",
    # Demo / promo — North America
    "SCCD", "SLCD",
    # Chinese / Taiwan
    "SCCS", "SLCS",
    # European special
    "SCZS",
    # Generic disc-ID variant
    "PBPX",
)

# ---------------------------------------------------------------------------
# Region mapping — serial prefix → human-readable region name
# ---------------------------------------------------------------------------

#: Maps each 4-letter serial prefix to its region string.
_PREFIX_TO_REGION: dict[str, str] = {
    # North America
    "SLUS": "NTSC-U", "SCUS": "NTSC-U",
    "SCCD": "NTSC-U", "SLCD": "NTSC-U",  # NA demo/promo
    # Europe / PAL
    "SLES": "PAL", "SCES": "PAL",
    "SLEH": "PAL", "SCEH": "PAL",
    "SLED": "PAL", "SCED": "PAL",  # PAL demo
    "SCZS": "PAL",                  # European special
    # Japan
    "SLPS": "NTSC-J", "SCPS": "NTSC-J",
    "SLPM": "NTSC-J", "SCPM": "NTSC-J",
    "SLPD": "NTSC-J", "SCPD": "NTSC-J",  # JP demo/promo
    # Korea
    "SLKA": "NTSC-K", "SCKA": "NTSC-K",
    # Asia (general)
    "SLAJ": "Asia",   "SCAJ": "Asia",
    "SCCS": "Asia",   "SLCS": "Asia",    # Chinese / Taiwan
}


def serial_to_region(serial: str) -> str:
    """Return the region name for *serial* (e.g. ``"NTSC-U"`` for ``"SLUS-…"``).

    Returns an empty string when the prefix is not recognised (e.g. ``"PBPX"``
    or an empty/invalid input).

    Examples::

        serial_to_region("SLUS-20062")  # -> "NTSC-U"
        serial_to_region("SLES-50000")  # -> "PAL"
        serial_to_region("SLPS-25000")  # -> "NTSC-J"
        serial_to_region("SLKA-10000")  # -> "NTSC-K"
        serial_to_region("")            # -> ""
    """
    if not serial:
        return ""
    return _PREFIX_TO_REGION.get(serial[:4].upper(), "")


# ---------------------------------------------------------------------------
# Serial detection regex
# ---------------------------------------------------------------------------

_PREFIX_GROUP = "|".join(re.escape(p) for p in SERIAL_PREFIXES)

_SERIAL_PATTERN = re.compile(
    r"(?<!\w)(" + _PREFIX_GROUP + r")[_\-]?(\d{5})(?!\d)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Known game serials → game title
# ---------------------------------------------------------------------------

# fmt: off
_KNOWN_SERIALS: dict[str, str] = {
    # ── North America (SLUS / SCUS) ──────────────────────────────────────────

    # Platformers / Action-Platformers
    "SLUS-20062": "Grand Theft Auto III",
    "SLUS-20183": "Spyro: Enter the Dragonfly",
    "SLUS-20439": "Spyro: A Hero's Tail",
    "SCUS-97124": "Jak and Daxter: The Precursor Legacy",
    "SCUS-97120": "Jak and Daxter: The Precursor Legacy",
    "SCUS-97265": "Jak II",
    "SCUS-97330": "Jak 3",
    "SCUS-97507": "Jak X: Combat Racing",
    "SCUS-97131": "Ratchet & Clank",
    "SCUS-97199": "Ratchet & Clank: Going Commando",
    "SCUS-97268": "Ratchet & Clank: Up Your Arsenal",
    "SCUS-97465": "Ratchet: Deadlocked",
    "SCUS-97198": "Sly Cooper and the Thievius Raccoonus",
    "SCUS-97404": "Sly 2: Band of Thieves",
    "SCUS-97492": "Sly 3: Honor Among Thieves",
    "SLUS-20238": "Crash Bandicoot: The Wrath of Cortex",
    "SLUS-20697": "Crash Twinsanity",
    "SLUS-21042": "Crash Tag Team Racing",
    "SLUS-21705": "Crash of the Titans",
    "SLUS-20164": "Klonoa 2: Lunatea's Veil",
    "SCUS-97129": "Ape Escape 2",
    "SCUS-97480": "Ape Escape 3",
    "SLUS-20258": "Mega Man X7",
    "SLUS-20879": "Mega Man X8",

    # Action / Adventure
    "SLUS-20891": "God of War",
    "SCUS-97399": "God of War",
    "SLUS-21441": "God of War II",
    "SCUS-97450": "God of War II",
    "SLUS-20721": "Shadow of the Colossus",
    "SCUS-97472": "Shadow of the Colossus",
    "SLUS-20678": "Ico",
    "SCUS-97113": "Ico",
    "SLUS-20487": "Devil May Cry",
    "SLUS-20626": "Devil May Cry 2",
    "SLUS-20902": "Devil May Cry 3: Dante's Awakening",
    "SLUS-21058": "Devil May Cry 3: Special Edition",
    "SLUS-20936": "Prince of Persia: The Sands of Time",
    "SLUS-21237": "Prince of Persia: The Two Thrones",
    "SLUS-21050": "Castlevania: Lament of Innocence",
    "SLUS-21173": "Castlevania: Curse of Darkness",

    # Stealth / Shooter
    "SLUS-20213": "Metal Gear Solid 2: Sons of Liberty",
    "SLUS-20554": "Metal Gear Solid 2: Substance",
    "SLUS-20718": "Metal Gear Solid 3: Snake Eater",
    "SLUS-20770": "Metal Gear Solid 3: Snake Eater (GH)",
    "SLUS-21070": "Metal Gear Solid 3: Subsistence",
    "SLUS-20584": "Tom Clancy's Splinter Cell",
    "SLUS-20842": "Tom Clancy's Splinter Cell: Pandora Tomorrow",
    "SLUS-21063": "Tom Clancy's Splinter Cell: Chaos Theory",
    "SLUS-21289": "Tom Clancy's Splinter Cell: Double Agent",
    "SLUS-20374": "Hitman 2: Silent Assassin",
    "SLUS-20775": "Hitman: Contracts",
    "SLUS-21210": "Hitman: Blood Money",
    "SCUS-97174": "SOCOM: U.S. Navy SEALs",
    "SCUS-97263": "SOCOM II: U.S. Navy SEALs",
    "SCUS-97346": "SOCOM 3: U.S. Navy SEALs",
    "SCUS-97429": "SOCOM: U.S. Navy SEALs Combined Assault",

    # Horror / Survival
    "SLUS-20228": "Silent Hill 2",
    "SLUS-20773": "Silent Hill 2 (GH)",
    "SLUS-20459": "Silent Hill 3",
    "SLUS-20507": "Silent Hill 3 (GH)",
    "SLUS-20978": "Silent Hill 4: The Room",
    "SLES-52232": "Silent Hill 4: The Room (PAL)",
    "SLUS-20184": "Resident Evil: Code Veronica X",
    "SLUS-21068": "Resident Evil 4",
    "SLUS-21134": "Resident Evil 4 (GH)",
    "SLUS-21616": "Resident Evil: Outbreak",
    "SLUS-21200": "Resident Evil: Dead Aim",

    # RPG
    "SLUS-20312": "Final Fantasy X",
    "SLUS-20672": "Final Fantasy X-2",
    "SLUS-20911": "Final Fantasy XII",
    "SLUS-20792": "Final Fantasy XII",
    "SLUS-21162": "Final Fantasy XII (Greatest Hits)",
    "SLUS-20370": "Kingdom Hearts",
    "SLUS-20552": "Kingdom Hearts",
    "SLUS-20145": "Kingdom Hearts",
    "SLUS-21005": "Kingdom Hearts II",
    "SLUS-21721": "Kingdom Hearts Re:Chain of Memories",
    "SLUS-21275": "Dragon Quest VIII: Journey of the Cursed King",
    "SLUS-20793": "Dragon Quest VIII: Journey of the Cursed King",
    "SLUS-21621": "Persona 3",
    "SLUS-21810": "Persona 3 FES",
    "SLUS-21310": "Persona 3 FES",
    "SLUS-21270": "Persona 3 FES",
    "SLUS-21922": "Persona 4",
    "SLUS-21370": "Persona 4",
    "SLUS-21277": "Okami",
    "SLUS-21597": "Okami",
    "SLUS-20453": "Xenosaga Episode I: Der Wille zur Macht",
    "SLUS-20831": "Xenosaga Episode II: Jenseits von Gut und Böse",
    "SLUS-21137": "Xenosaga Episode III: Also Sprach Zarathustra",
    "SLUS-20272": "Wild Arms 3",
    "SLUS-21067": "Wild Arms 4",
    "SLUS-21475": "Wild Arms 5",
    "SLUS-20472": "Suikoden III",
    "SLUS-20963": "Suikoden IV",
    "SLUS-21291": "Suikoden V",
    "SLUS-20428": "Shadow Hearts",
    "SLUS-20973": "Shadow Hearts: Covenant",
    "SLUS-21494": "Shadow Hearts: From the New World",
    "SLUS-21591": "Rogue Galaxy",
    "SCUS-97121": "Dark Cloud",
    "SCUS-97331": "Dark Chronicle (Dark Cloud 2)",
    "SLUS-21020": "Shin Megami Tensei: Digital Devil Saga",
    "SLUS-21194": "Shin Megami Tensei: Digital Devil Saga 2",
    "SLUS-20565": "Disgaea: Hour of Darkness",
    "SLUS-21440": "Disgaea 2: Cursed Memories",
    "SLUS-21683": "Disgaea 3: Absence of Justice",
    "SLUS-21156": "Makai Kingdom: Chronicles of the Sacred Tome",
    "SLUS-21480": "Phantom Brave: We Meet Again",
    "SLUS-20365": "Disgaea: Hour of Darkness",
    "SLUS-21150": "Radiata Stories",
    "SLUS-20945": "Growlanser Generations",
    "SLUS-21052": "Atelier Iris: Eternal Mana",
    "SLUS-21350": "Atelier Iris 2: The Azoth of Destiny",
    "SLUS-21614": "Atelier Iris 3: Grand Phantasm",
    "SLUS-21490": ".hack//G.U. Vol. 1//Rebirth",
    "SLUS-21618": ".hack//G.U. Vol. 2//Reminisce",
    "SLUS-21750": ".hack//G.U. Vol. 3//Redemption",
    "SLUS-20056": ".hack//Infection",
    "SLUS-20772": "Baldur's Gate: Dark Alliance",
    "SLUS-20803": "Baldur's Gate: Dark Alliance II",
    "SLUS-20789": "Champions of Norrath: Realms of EverQuest",
    "SLUS-20536": "Star Ocean: Till the End of Time",
    "SLUS-21205": "Star Ocean: Till the End of Time Director's Cut",
    "SLUS-20957": "Tales of the Abyss",
    "SLUS-20594": "Tales of Legendia",
    "SLUS-20727": "Ico and Shadow of the Colossus: The ICO & Shadow of the Colossus Collection",
    "SLUS-21580": "NieR Replicant",

    # Racing / Sports
    "SLUS-20486": "Gran Turismo 3: A-spec",
    "SCUS-97102": "Gran Turismo 3: A-spec",
    "SLUS-21163": "Gran Turismo 4",
    "SCUS-97436": "Gran Turismo 4",
    "SLUS-20444": "Grand Theft Auto: San Andreas",
    "SLUS-20688": "Grand Theft Auto: San Andreas (v2)",
    "SLUS-20140": "Grand Theft Auto: Vice City",
    "SLUS-20946": "Grand Theft Auto: San Andreas",
    "SLUS-20769": "Grand Theft Auto III",
    "SLUS-21154": "Grand Theft Auto: Liberty City Stories",
    "SLUS-20590": "Need for Speed: Underground",
    "SLUS-20811": "Need for Speed: Underground 2",
    "SLUS-21202": "Need for Speed: Most Wanted",
    "SLUS-21399": "Need for Speed: Carbon",
    "SLUS-21658": "Need for Speed: ProStreet",
    "SLUS-21077": "Burnout 3: Takedown",
    "SLUS-21197": "Burnout Revenge",
    "SLUS-21708": "Burnout Dominator",
    "SLUS-20301": "SSX Tricky",
    "SLUS-20783": "SSX 3",
    "SLUS-21201": "SSX On Tour",
    "SLUS-20458": "Midnight Club II",
    "SLUS-21062": "Midnight Club 3: DUB Edition",
    "SLUS-21342": "Midnight Club 3: DUB Edition (Remix)",
    "SLUS-20001": "Ridge Racer V",
    "SLUS-20322": "Wipeout Fusion",
    "SLUS-20537": "Wipeout Pulse",
    "SLUS-20095": "Tony Hawk's Pro Skater 3",
    "SLUS-20480": "Tony Hawk's Pro Skater 4",
    "SLUS-20731": "Tony Hawk's Underground",
    "SLUS-20907": "Tony Hawk's Underground 2",
    "SLUS-21079": "Tony Hawk's American Wasteland",

    # Music / Rhythm
    "SLUS-20940": "Guitar Hero",
    "SLUS-21323": "Guitar Hero II",
    "SLUS-21426": "Guitar Hero III: Legends of Rock",
    "SLUS-21669": "Guitar Hero: Aerosmith",
    "SLUS-21768": "Guitar Hero: World Tour",
    "SLUS-21888": "Guitar Hero: Metallica",
    "SLUS-21145": "Karaoke Revolution",
    "SLUS-20327": "Amplitude",
    "SLUS-20578": "Frequency",

    # Fighting
    "SLUS-20162": "Tekken Tag Tournament",
    "SLUS-20328": "Tekken 4",
    "SLUS-20882": "Tekken 4",
    "SLUS-21085": "Tekken 5",
    "SLUS-21219": "Tekken 5",
    "SLUS-21847": "Tekken 5: Dark Resurrection",
    "SLUS-20591": "SoulCalibur II",
    "SLUS-20574": "SoulCalibur II",
    "SLUS-20488": "Mortal Kombat: Deadly Alliance",
    "SLUS-20881": "Mortal Kombat: Deception",
    "SLUS-21420": "Mortal Kombat: Armageddon",
    "SLUS-20609": "Virtua Fighter 4: Evolution",
    "SLUS-20084": "Dead or Alive 2: Hardcore",
    "SLUS-20446": "Capcom vs. SNK 2: Mark of the Millennium 2001",
    "SLUS-20762": "Street Fighter Alpha Anthology",
    "SLUS-20916": "Guilty Gear X2: The Midnight Carnival",
    "SLUS-21472": "Dragon Ball Z: Budokai Tenkaichi 3",
    "SLUS-21678": "Dragon Ball Z: Budokai Tenkaichi 3",
    "SLUS-21353": "Dragon Ball Z: Budokai Tenkaichi 2",
    "SLUS-21028": "Dragon Ball Z: Budokai 3",
    "SLUS-20821": "Dragon Ball Z: Budokai 2",
    "SLUS-20974": "Naruto: Ultimate Ninja",
    "SLUS-21575": "Naruto: Ultimate Ninja 3",

    # Action / Open World / Sandbox
    "SLUS-21131": "Bully",
    "SLUS-21168": "The Warriors",
    "SLUS-20625": "Mafia",
    "SLUS-21006": "The Godfather: The Game",
    "SLUS-20636": "Jak and Daxter: The Precursor Legacy",
    "SLUS-21022": "True Crime: New York City",

    # Sci-Fi / Mech
    "SLUS-20403": "Armored Core 2",
    "SLUS-21177": "Armored Core: Nine Breaker",
    "SLUS-20515": "Zone of the Enders",
    "SLUS-20541": "Zone of the Enders: The 2nd Runner",

    # War / Shooter
    "SLUS-20038": "Star Wars: Battlefront",
    "SLUS-21240": "Star Wars: Battlefront II",
    "SLUS-20299": "Medal of Honor: Frontline",
    "SLUS-20820": "Medal of Honor: Rising Sun",
    "SLUS-21218": "Medal of Honor: European Assault",
    "SLUS-20432": "Call of Duty 2: Big Red One",
    "SLUS-20845": "Killzone",

    # Family / Action-Adventure
    "SLUS-21228": "Eragon",
    "SLES-54053": "Eragon (PAL)",
    "SLUS-21238": "Neopets: The Darkest Fairy",
    "SCES-54023": "Neopets: The Darkest Fairy (PAL)",

    # Simulation / Strategy
    "SLUS-21102": "The Sims 2",
    "SLUS-21668": "The Sims 2: Castaway",
    "SLUS-20469": "Harvest Moon: Save the Homeland",
    "SLUS-21234": "Harvest Moon: A Wonderful Life Special Edition",

    # Sports
    "SLUS-21024": "WWE SmackDown! vs. RAW 2006",
    "SLUS-21497": "WWE SmackDown! vs. RAW 2008",
    "SLUS-20787": "WWE SmackDown! Here Comes the Pain",
    "SLUS-20427": "WWE SmackDown! Shut Your Mouth",
    "SLUS-20901": "WWE SmackDown! vs. RAW",
    "SLUS-20415": "NBA Street Vol. 2",
    "SLUS-20915": "NBA Street Vol. 3",
    "SCUS-97123": "Hot Shots Golf 3",
    "SCUS-97216": "ATV Off-Road Fury 2",
    "SCUS-97334": "ATV Off-Road Fury 3",
    "SCUS-97470": "ATV Off-Road Fury 4",

    # Action / Open World
    "SLUS-20671": "Mafia",
    "SLUS-20853": "Manhunt",
    "SLUS-21179": "Indigo Prophecy",

    # Action / Combat
    "SLUS-20776": "Spider-Man 2",
    "SLUS-21262": "Ultimate Spider-Man",
    "SLUS-20492": "Contra: Shattered Soldier",
    "SLUS-20765": "Resident Evil Outbreak",
    "SLUS-21243": "Resident Evil Outbreak File #2",

    # Skateboarding / Sports Action
    "SLUS-20782": "Tony Hawk's Underground",
    "SLUS-21256": "Tony Hawk's American Wasteland",
    "SCUS-97731": "Tony Hawk's Project 8",

    # Platform
    "SLUS-20683": "SpongeBob SquarePants: Battle for Bikini Bottom",
    "SLUS-20685": "Ape Escape 2",
    "SCUS-97501": "Ape Escape 3",

    # Mecha / Action
    "SLUS-20392": "Armored Core 3",
    "SLUS-20715": "Armored Core: Silent Line",
    "SLUS-20938": "Armored Core: Nexus",
    "SLUS-21456": "Armored Core: Last Raven",

    # Racing
    "SLUS-21242": "Burnout Revenge",
    "SLUS-20462": "Burnout 3: Takedown",

    # JRPG / RPG
    "SLUS-20048": "Grandia II",
    "SLUS-21516": "Grandia III",
    "SLUS-21430": "Ar tonelico: Melody of Elemia",
    "SLUS-21765": "Ar tonelico II: Melody of Metafalica",
    "SLUS-21667": "Soul Nomad & the World Eaters",
    "SLUS-21174": "We Love Katamari",
    "SLUS-21171": "Haunting Ground",
    "SLUS-20981": "Viewtiful Joe",
    "SLUS-21065": "Viewtiful Joe 2",
    "SLUS-20854": "Shadow Hearts: Covenant",
    "SLUS-21266": "Shadow Hearts: From the New World",
    "SLUS-20743": "Arc the Lad: Twilight of the Spirits",
    "SLUS-20892": "Xenosaga Episode II",
    "SLUS-21382": "Xenosaga Episode III",
    "SLUS-21033": "Tales of Symphonia",
    "SLUS-21858": "Tales of Legendia",
    "SLUS-20858": "Tales of Destiny",
    "SLUS-21023": "Wild Arms: Alter Code F",
    "SLUS-21383": "Wild Arms 4",
    "SLUS-21749": "Wild Arms 5",
    "SLUS-20292": "Suikoden III",
    "SLUS-20895": "Suikoden IV",
    "SLUS-21354": "Persona 3",
    "SLUS-20443": "Devil May Cry 2",
    "SLUS-21216": "Devil May Cry 3: Special Edition",
    "SLUS-20216": "Zone of the Enders",
    "SLUS-20553": "Zone of the Enders: The 2nd Runner",
    "SLUS-21060": "Fatal Frame",
    "SLUS-20825": "Fatal Frame II: Crimson Butterfly",
    "SLUS-21161": "Fatal Frame III: The Tormented",
    "SLUS-20519": "Baldur's Gate: Dark Alliance",
    "SLUS-20846": "Baldur's Gate: Dark Alliance II",

    # ── Europe — PAL (SLES / SCES) ────────────────────────────────────────────

    # Action / Adventure
    "SCES-53133": "God of War (PAL)",
    "SCES-54803": "God of War II (PAL)",
    "SCES-53326": "Shadow of the Colossus (PAL)",
    "SCES-53005": "Shadow of the Colossus (PAL)",
    "SCES-50760": "Ico (PAL)",
    "SLES-50873": "Devil May Cry (PAL)",
    "SLES-51619": "Clock Tower 3 (PAL)",
    "SLES-52806": "Devil May Cry 3: Dante's Awakening (PAL)",
    "SLES-53670": "Devil May Cry 3: Special Edition (PAL)",
    "SLES-52171": "Prince of Persia: The Sands of Time (PAL)",
    "SLES-52726": "Prince of Persia: Warrior Within (PAL)",
    "SLES-53741": "Prince of Persia: The Two Thrones (PAL)",
    "SLES-51044": "Castlevania: Lament of Innocence (PAL)",
    "SLES-53432": "Castlevania: Curse of Darkness (PAL)",

    # Stealth / Horror
    "SLES-50383": "Metal Gear Solid 2: Sons of Liberty (PAL)",
    "SLES-51290": "Metal Gear Solid 2: Substance (PAL)",
    "SLES-52557": "Metal Gear Solid 3: Snake Eater (PAL)",
    "SLES-54236": "Metal Gear Solid 3: Subsistence (PAL)",
    "SLES-50356": "Silent Hill 2 (PAL)",
    "SLES-51428": "Silent Hill 3 (PAL)",
    "SLES-52177": "Silent Hill 4: The Room (PAL)",
    "SLES-51748": "Resident Evil Code: Veronica X (PAL)",
    "SLES-53702": "Resident Evil 4 (PAL)",

    # RPG
    "SLES-50490": "Final Fantasy X (PAL)",
    "SLES-51818": "Final Fantasy X-2 (PAL)",
    "SLES-54354": "Final Fantasy XII (PAL)",
    "SLES-51152": "Kingdom Hearts (PAL)",
    "SLES-54114": "Kingdom Hearts II (PAL)",
    "SLES-53831": "Dragon Quest VIII (PAL)",
    "SLES-54327": "Persona 3 FES (PAL)",
    "SLES-55228": "Persona 4 (PAL)",
    "SLES-54289": "Okami (PAL)",
    "SLES-52959": "Star Ocean: Till the End of Time (PAL)",
    "SLES-53628": "Tales of the Abyss (PAL)",
    "SLES-53693": "Suikoden V (PAL)",
    "SLES-53662": "Baldur's Gate: Dark Alliance II (PAL)",
    "SLES-51642": "Baldur's Gate: Dark Alliance (PAL)",

    # Racing
    "SCES-50294": "Gran Turismo 3: A-spec (PAL)",
    "SCES-51719": "Gran Turismo 4 (PAL)",
    "SLES-51999": "Grand Theft Auto: Vice City (PAL)",
    "SLES-52927": "Grand Theft Auto: San Andreas (PAL)",
    "SLES-50978": "Need for Speed: Underground (PAL)",
    "SLES-52725": "Need for Speed: Underground 2 (PAL)",
    "SLES-53816": "Need for Speed: Most Wanted (PAL)",
    "SLES-54586": "Burnout 3: Takedown (PAL)",
    "SLES-53353": "Burnout 3: Takedown (PAL)",

    # Platformers (PAL)
    "SCES-50608": "Jak and Daxter: The Precursor Legacy (PAL)",
    "SCES-51607": "Jak II (PAL)",
    "SCES-52456": "Jak 3 (PAL)",
    "SCES-50391": "Ratchet & Clank (PAL)",
    "SLES-51176": "Crash Bandicoot: The Wrath of Cortex (PAL)",
    "SLES-52606": "Crash Twinsanity (PAL)",
    "SCES-50800": "Sly Racoon (PAL)",
    "SCES-52009": "Sly 2: Band of Thieves (PAL)",

    # Fighting (PAL)
    "SLES-50761": "Tekken Tag Tournament (PAL)",
    "SLES-51552": "Tekken 4 (PAL)",
    "SLES-53014": "Tekken 5 (PAL)",
    "SCES-52423": "SoulCalibur II (PAL)",
    "SLES-54267": "SoulCalibur III (PAL)",
    "SLES-51483": "Mortal Kombat: Deadly Alliance (PAL)",
    "SLES-52705": "Mortal Kombat: Deception (PAL)",

    # ── Japan (SLPS / SCPS) ───────────────────────────────────────────────────

    # Racing
    "SCPS-15009": "Gran Turismo 3: A-spec (JP)",
    "SCPS-17001": "Gran Turismo 4 (JP)",
    "SLPS-25516": "Gran Turismo 4 (JP)",

    # RPG
    "SLPS-25088": "Kingdom Hearts (JP)",
    "SLPS-25609": "Final Fantasy XII (JP)",
    "SLPS-25520": "Final Fantasy XII (JP)",
    "SCPS-11074": "Final Fantasy X (JP)",
    "SLPS-25016": "Final Fantasy X (JP)",
    "SLPS-25337": "Final Fantasy X-2 (JP)",
    "SLPS-25642": "Kingdom Hearts II Final Mix (JP)",
    "SLPS-25605": "Kingdom Hearts II (JP)",
    "SLPS-25281": "Dragon Quest VIII (JP)",
    "SLPS-25100": "Dark Cloud (JP)",
    "SLPS-25215": "Dark Chronicle (JP)",
    "SLPS-25244": "Rogue Galaxy (JP)",
    "SLPM-66244": "Okami (JP)",
    "SLPS-25191": "Shadow Hearts (JP)",
    "SLPS-25362": "Shadow Hearts: Covenant (JP)",
    "SLPM-65820": "Persona 3 (JP)",
    "SLPM-65892": "Persona 3 FES (JP)",
    "SLPM-66412": "Persona 4 (JP)",
    "SLPS-25382": "Xenosaga Episode I (JP)",
    "SLPS-25451": "Xenosaga Episode II (JP)",
    "SLPS-25653": "Xenosaga Episode III (JP)",
    "SLPS-20005": ".hack//Infection (JP)",
    "SLPS-20061": ".hack//Mutation (JP)",
    "SLPS-20102": ".hack//Outbreak (JP)",
    "SLPS-20152": ".hack//Quarantine (JP)",
    "SLPS-25820": ".hack//G.U. Vol. 1//Rebirth (JP)",
    "SLPS-25867": ".hack//G.U. Vol. 2//Reminisce (JP)",
    "SLPS-25919": ".hack//G.U. Vol. 3//Redemption (JP)",

    # Action
    "SCPS-11012": "Ico (JP)",
    "SCPS-17003": "Shadow of the Colossus (JP)",
    "SLPS-20066": "Devil May Cry (JP)",
    "SLPS-25105": "Devil May Cry 2 (JP)",
    "SLPS-25314": "Devil May Cry 3 (JP)",
    "SLPS-25463": "God of War (JP)",
    "SLPS-25675": "God of War II (JP)",
    "SLPS-25252": "Metal Gear Solid 2: Sons of Liberty (JP)",
    "SLPM-65792": "Metal Gear Solid 3: Snake Eater (JP)",

    # Fighting
    "SLPS-25262": "Tekken 4 (JP)",
    "SLPS-25579": "Tekken 5 (JP)",
    "SLPS-25170": "SoulCalibur II (JP)",
    "SLPS-25734": "SoulCalibur III (JP)",

    # Platformers
    "SCPS-15024": "Jak and Daxter: The Precursor Legacy (JP)",
    "SCPS-15033": "Ratchet & Clank (JP)",
    "SLPS-25143": "Crash Bandicoot: The Wrath of Cortex (JP)",
    "SLPS-25265": "Crash Twinsanity (JP)",

    # ── Korea (SLKA / SCKA) ───────────────────────────────────────────────────
    "SLKA-25072": "Gran Turismo 3: A-spec (KR)",
    "SLKA-25104": "Gran Turismo 4 (KR)",
    "SLKA-25053": "Kingdom Hearts (KR)",
    "SLKA-25246": "Kingdom Hearts II (KR)",
    "SLKA-25297": "Tekken 5 (KR)",
    "SLKA-25192": "Tekken 4 (KR)",
    "SLKA-25065": "Devil May Cry (KR)",
    "SLKA-25169": "Devil May Cry 2 (KR)",
    "SLKA-25278": "SoulCalibur II (KR)",
    "SLKA-25394": "SoulCalibur III (KR)",
    "SCKA-20001": "Gran Turismo 3: A-spec (KR Alt)",
    "SLKA-25187": "Resident Evil 4 (KR)",
    "SLKA-25324": "Shadow of the Colossus (KR)",
    "SLKA-25276": "Ico (KR)",
    "SLKA-25323": "Star Ocean: Till the End of Time (KR)",

    # ── Asia (SLAJ / SCAJ) ────────────────────────────────────────────────────
    "SCAJ-20065": "Gran Turismo 4 (AS)",
    "SLAJ-25018": "Kingdom Hearts (AS)",
    "SLAJ-25048": "Kingdom Hearts II (AS)",
    "SCAJ-20011": "Gran Turismo 3: A-spec (AS)",
    "SLAJ-25061": "Devil May Cry (AS)",
    "SLAJ-25135": "Devil May Cry 2 (AS)",
    "SLAJ-25259": "Devil May Cry 3 (AS)",
    "SLAJ-25027": "Resident Evil Code: Veronica X (AS)",
    "SLAJ-25076": "Resident Evil 4 (AS)",
    "SLAJ-25029": "Ico (AS)",
    "SLAJ-25105": "Shadow of the Colossus (AS)",
    "SLAJ-25053": "SoulCalibur II (AS)",
    "SLAJ-25186": "SoulCalibur III (AS)",
    "SLAJ-25014": "Final Fantasy X (AS)",
    "SLAJ-25068": "Final Fantasy X-2 (AS)",
    "SLAJ-25172": "Final Fantasy XII (AS)",

    # ── Additional PAL / Europe (SLES / SCES) ─────────────────────────────────

    "SLES-51128": "Ico (PAL)",
    "SLES-50966": "Silent Hill 2 (PAL)",
    "SLES-51434": "Silent Hill 3 (PAL)",
    "SLES-52777": "Silent Hill 4: The Room (PAL)",
    "SLES-50300": "Devil May Cry (PAL)",
    "SLES-51265": "Devil May Cry 2 (PAL)",
    "SLES-52286": "Devil May Cry 3 (PAL)",
    "SCES-50917": "Jak and Daxter: The Precursor Legacy (PAL)",
    "SCES-51608": "Jak II: Renegade (PAL)",
    "SCES-52460": "Jak 3 (PAL)",
    "SCES-50916": "Ratchet & Clank (PAL)",
    "SCES-53440": "Gran Turismo 4: Prologue (PAL)",
    "SCES-52878": "Tekken 5 (PAL)",
    "SLES-52972": "Burnout Revenge (PAL)",
    "SCES-54423": "Sly Raccoon (PAL)",
    "SCES-52836": "Sly 2: Band of Thieves (PAL)",
    "SCES-53794": "Sly 3: Honour Among Thieves (PAL)",
    "SLES-50825": "Baldur's Gate: Dark Alliance (PAL)",
    "SLES-54495": "Persona 3 FES (PAL)",
    "SLES-55283": "Persona 4 (PAL)",
    "SLES-52537": "Kingdom Hearts (PAL)",
    "SLES-54154": "Kingdom Hearts II (PAL)",
    "SCES-52946": "Buzz! The Big Quiz (PAL)",
    "SCES-53372": "SingStar (PAL)",
    "SCES-53139": "EyeToy: Play (PAL)",
    "SLES-51277": "TimeSplitters 2 (PAL)",
    "SLES-53033": "TimeSplitters: Future Perfect (PAL)",
    "SLES-51450": "Star Wars: Battlefront (PAL)",
    "SLES-53070": "Star Wars: Battlefront II (PAL)",
    "SLES-53982": "Pro Evolution Soccer 6 (PAL)",
    "SLES-51719": "Burnout 3: Takedown (PAL)",
    "SLES-51459": "WWE SmackDown! vs. Raw (PAL)",
    "SLES-52546": "WWE SmackDown! vs. Raw 2006 (PAL)",

    # ── Additional Japan (SLPS / SCPS) ────────────────────────────────────────

    "SCPS-11001": "Gran Turismo 3: A-spec (JP)",
    "SLPS-25017": "Ico (JP)",
    "SCPS-15039": "Shadow of the Colossus (JP)",
    "SLPS-25119": "Kessen (JP)",
    "SLPS-25069": "Kessen II (JP)",
    "SLPS-25128": "Kessen III (JP)",
    "SLPS-25099": "Onimusha: Warlords (JP)",
    "SLPS-25194": "Onimusha 2: Samurai's Destiny (JP)",
    "SLPS-25195": "Onimusha 3: Demon Siege (JP)",
    "SLPS-25401": "Onimusha: Dawn of Dreams (JP)",
    "SLPS-25147": "Devil May Cry 2 (JP)",
    "SLPS-25270": "Devil May Cry 3 (JP)",
    "SLPS-25154": "Silent Hill 3 (JP)",
    "SLPS-25263": "Silent Hill 4: The Room (JP)",
    "SLPS-25229": "Fatal Frame II (JP)",
    "SLPS-25292": "Fatal Frame III (JP)",
    "SLPM-65904": "Star Ocean: Till the End of Time (JP)",
    "SLPM-65350": "Persona 3 (JP)",
    "SLPM-66760": "Persona 4 (JP)",
    "SLPM-65017": "Suikoden III (JP)",
    "SLPM-65444": "Suikoden IV (JP)",
    "SLPM-66066": "Suikoden V (JP)",
    "SLPS-25315": "Dragon Quest VIII: Journey of the Cursed King (JP)",
    "SLPM-65970": "Tales of the Abyss (JP)",
    "SLPM-66051": "Tales of Legendia (JP)",
    "SLPM-66122": "Tales of Destiny: Director's Cut (JP)",
    "SCPS-19001": "Tekken Tag Tournament (JP)",
    "SCPS-15022": "Tekken 4 (JP)",
    "SCPS-15063": "Tekken 5 (JP)",
    "SLPM-65895": "SoulCalibur II (JP)",
    "SLPM-66183": "SoulCalibur III (JP)",
    "SLPS-25219": "Virtua Fighter 4 (JP)",
    "SLPS-25332": "Virtua Fighter 4: Evolution (JP)",
    "SLPM-65035": "Dragon Ball Z: Budokai (JP)",
    "SLPM-65442": "Dragon Ball Z: Budokai 2 (JP)",
    "SLPM-65768": "Dragon Ball Z: Budokai 3 (JP)",
    "SLPM-65879": "Dragon Ball Z: Budokai Tenkaichi (JP)",
    "SLPM-66229": "Dragon Ball Z: Budokai Tenkaichi 2 (JP)",
    "SLPM-66590": "Dragon Ball Z: Budokai Tenkaichi 3 (JP)",
    "SLPM-65013": "Disgaea: Hour of Darkness (JP)",
    "SLPM-65519": "Disgaea 2: Cursed Memories (JP)",
    "SLPM-66293": "Disgaea 3: Absence of Justice (JP)",
    "SLPS-25387": "Winning Eleven 9 (JP)",
    "SLPM-66069": "Romance of the Three Kingdoms XI (JP)",
    "SLPM-66413": "Valkyria Chronicles (JP)",

    # ── Additional US serials for cover-art entries ───────────────────────────

    # Action / Adventure
    "SCUS-97481": "God of War II",
    "SLUS-20785": "Metal Gear Solid 3: Snake Eater",
    "SLUS-20144": "Metal Gear Solid 2: Sons of Liberty",

    # RPG
    "SLUS-21819": "Persona 4",
    "SLUS-21115": "Okami",
    "SLUS-21207": "Dragon Quest VIII: Journey of the Cursed King",
    "SLUS-20461": "Xenosaga Episode I: Der Wille zur Macht",
    "SLUS-21386": "Tales of the Abyss",
    "SLUS-20734": "Star Ocean: Till the End of Time",
    "SLUS-21299": "Valkyrie Profile 2: Silmeria",
    "SLUS-21652": "Ar tonelico: Melody of Elemia",
    "SLUS-21720": "Soul Nomad and the World Eaters",
    "SLUS-21281": "Grandia III",

    # Platform / Action
    "SCUS-97490": "Rogue Galaxy",
    "SLUS-20816": "Sly 2: Band of Thieves",
    "SLUS-20518": "Crash Bandicoot: The Wrath of Cortex",
    "SCUS-97213": "Dark Cloud 2",
    "SLUS-21435": "We Love Katamari",
    "SLUS-20108": "Spyro: Enter the Dragonfly",

    # Horror / Action
    "SLUS-20934": "Fatal Frame II: Crimson Butterfly",
    "SLUS-20827": "Manhunt",
    "SLUS-21181": "Indigo Prophecy",

    # Mech / Sci-fi
    "SLUS-20355": "Armored Core 3",

    # Open World
    "SLUS-20069": "Grand Theft Auto III",

    # Japan-only
    "SLPS-25563": "Tales of Symphonia (JP)",

    # Shooter / Action
    "SLUS-20568": "Contra: Shattered Soldier",

    # ── Additional serials for texture/PNACH/save catalogue entries ──────────

    # Action RPG
    "SLUS-20707": "Drakengard",
    "SLUS-21134": "Drakengard 2",

    # Shoot-em-up
    "SLUS-21080": "Gradius V",

    # Horror
    "SLUS-20700": "Forbidden Siren",
    "SLES-53853": "Forbidden Siren 2 (PAL)",

    # Open World
    "SLUS-21590": "Grand Theft Auto: Vice City Stories",

    # Action Adventure
    "SLUS-20959": "Beyond Good & Evil",

    # Shooter
    "SLUS-20898": "Star Wars: Battlefront",

    # Racing
    "SLUS-20489": "Burnout 2: Point of Impact",

    # Sports / Wrestling
    "SLUS-21302": "WWE SmackDown! vs. RAW 2006",
    "SLUS-21424": "WWE SmackDown vs. RAW 2007",

    # Platform
    "SLUS-21282": "Ape Escape 3",
    "SLUS-21372": "The Legend of Spyro: A New Beginning",
    "SCES-02705": "Crash Bash (PAL)",

    # Action
    "SLUS-21322": "Viewtiful Joe: Red Hot Rumble",

    # Racing
    "SCUS-97328": "Gran Turismo 4",
}
# fmt: on

# ---------------------------------------------------------------------------
# Enrich _KNOWN_SERIALS with the PAL/European JSON database
# ---------------------------------------------------------------------------
def _load_pal_serials() -> dict[str, str]:
    """Load PAL serial → title mappings from ps2_pal.json."""
    import json as _json
    _pal_db = Path(__file__).parent.parent.parent / "data" / "game_serial_db" / "ps2_pal.json"
    if not _pal_db.is_file():
        return {}
    try:
        raw = _json.loads(_pal_db.read_text(encoding="utf-8"))
    except Exception:
        return {}
    result: dict[str, str] = {}
    for title, info in raw.get("games", {}).items():
        serial = info.get("serial", "")
        if serial:
            result[serial] = title
        for alt in info.get("alt_serials", []):
            if alt and alt not in result:
                result[alt] = title
    return result


def _load_japan_serials() -> dict[str, str]:
    """Load Japan (NTSC-J) serial → title mappings from ps2_japan.json."""
    import json as _json
    _jp_db = Path(__file__).parent.parent.parent / "data" / "game_serial_db" / "ps2_japan.json"
    if not _jp_db.is_file():
        return {}
    try:
        raw = _json.loads(_jp_db.read_text(encoding="utf-8"))
    except Exception:
        return {}
    result: dict[str, str] = {}
    for title, info in raw.get("games", {}).items():
        serial = info.get("serial", "")
        if serial:
            result[serial] = title
        for alt in info.get("alt_serials", []):
            if alt and alt not in result:
                result[alt] = title
    return result


def _load_ntsc_u_serials() -> dict[str, str]:
    """Load NTSC-U serial → title mappings from ps2_ntsc_u.json (issue #23)."""
    import json as _json
    _db = Path(__file__).parent.parent.parent / "data" / "game_serial_db" / "ps2_ntsc_u.json"
    if not _db.is_file():
        return {}
    try:
        raw = _json.loads(_db.read_text(encoding="utf-8"))
    except Exception:
        return {}
    result: dict[str, str] = {}
    for title, info in raw.get("games", {}).items():
        serial = info.get("serial", "")
        if serial:
            result[serial] = title
        for alt in info.get("alt_serials", []):
            if alt and alt not in result:
                result[alt] = title
    return result


def _load_demos_serials() -> dict[str, str]:
    """Load PS2 demo serial → title mappings from ps2_demos.json."""
    import json as _json
    _db = Path(__file__).parent.parent.parent / "data" / "game_serial_db" / "ps2_demos.json"
    if not _db.is_file():
        return {}
    try:
        raw = _json.loads(_db.read_text(encoding="utf-8"))
    except Exception:
        return {}
    result: dict[str, str] = {}
    for title, info in raw.get("games", {}).items():
        serial = info.get("serial", "")
        if serial:
            result[serial] = title
        for alt in info.get("alt_serials", []):
            if alt and alt not in result:
                result[alt] = title
    return result


def _load_informative_serials(base_dir: Optional[Path] = None) -> dict[str, str]:
    """Load additional serial → title mappings from informative-document JSON files."""
    import json as _json
    import html as _html
    root = base_dir or (Path(__file__).parent.parent.parent / "Informative doccument")
    serial_re = re.compile(r"^[A-Z]{4}-\d{5}$")
    result: dict[str, str] = {}

    # JSON maps: {serial: title} and {serial: {title: ...}}
    for fp in (root / "PS2.data.json", root / "Ps2 codes and names 3.json"):
        if not fp.is_file():
            continue
        try:
            raw = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        for key, value in raw.items():
            serial = str(key).strip().upper().replace("_", "-")
            if not serial_re.match(serial):
                continue
            if serial.endswith("-99999"):
                continue
            if isinstance(value, str):
                title = value.strip()
            elif isinstance(value, dict):
                title = str(value.get("title", "")).strip()
            else:
                title = ""
            if title and serial not in result:
                result[serial] = title

    # TXT map: "SERIAL<TAB>TITLE"
    txt_fp = root / "PS2 codes and name 4.txt"
    if txt_fp.is_file():
        try:
            for raw_line in txt_fp.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                parts = line.split("\t", 1)
                if len(parts) != 2:
                    continue
                serial = parts[0].strip().upper().replace("_", "-")
                title = parts[1].strip()
                if serial.endswith("-99999"):
                    continue
                if serial_re.match(serial) and title and serial not in result:
                    result[serial] = title
        except Exception:
            pass

    # HTML table: first <td> is title, GAME ID appears in a <center> cell.
    htm_fp = root / "PS2.ID.List.02.13.20.htm"
    if htm_fp.is_file():
        try:
            html_text = htm_fp.read_text(encoding="utf-8", errors="replace")
            row_re = re.compile(
                r"<tr><td>(.*?)</td>.*?<center>\s*([A-Z]{4}[-_]\d{5})\s*</center>",
                re.IGNORECASE | re.DOTALL,
            )
            strip_tags_re = re.compile(r"<[^>]+>")
            for title_cell, serial_raw in row_re.findall(html_text):
                serial = serial_raw.strip().upper().replace("_", "-")
                if not serial_re.match(serial) or serial in result:
                    continue
                if serial.endswith("-99999"):
                    continue
                title = _html.unescape(strip_tags_re.sub("", title_cell)).strip()
                if title:
                    result[serial] = title
        except Exception:
            pass
    return result


# Preserve the curated hardcoded entries so they can be re-applied with
# higher priority after merging in the JSON databases.  This ensures that
# well-known serials in the hardcoded dict are never clobbered by
# incorrect or conflicting entries in the JSON serial databases.
_hardcoded_serials = dict(_KNOWN_SERIALS)
_KNOWN_SERIALS.update(_load_pal_serials())
_KNOWN_SERIALS.update(_load_japan_serials())
_KNOWN_SERIALS.update(_load_ntsc_u_serials())
_KNOWN_SERIALS.update(_load_demos_serials())
for _serial, _title in _load_informative_serials().items():
    _KNOWN_SERIALS.setdefault(_serial, _title)
# Hardcoded entries take final priority over any JSON DB entry.
_KNOWN_SERIALS.update(_hardcoded_serials)


def detect_game_serial(filename: str, file_content: Optional[bytes] = None) -> str:
    """
    Attempt to detect a PS2 game serial from a filename (and optionally
    the first few KB of file content).

    Returns the normalised serial (e.g. ``"SLUS-20062"``), or an empty
    string if no serial is found.

    Normalisation: upper-case, separator always ``-`` (not ``_``).
    """
    # 1. Try the filename
    stem = Path(filename).stem
    serial = _parse_serial(stem)
    if serial:
        return serial

    # Also try the full path
    full = str(filename)
    serial = _parse_serial(full)
    if serial:
        return serial

    # 2. Optionally scan the first 4 KB of file content (e.g. text-based PNACH)
    if file_content:
        try:
            text = file_content[:4096].decode("utf-8", errors="ignore")
            serial = _parse_serial(text)
            if serial:
                return serial
        except Exception:
            pass

    return ""


def _parse_serial(text: str) -> str:
    """Extract and normalise the first PS2 serial found in *text*."""
    m = _SERIAL_PATTERN.search(text)
    if not m:
        return ""
    region = m.group(1).upper()
    number = m.group(2)
    return f"{region}-{number}"


def detect_game_serial_from_file(path: str) -> str:
    """
    Detect the PS2 game serial from a file path.
    Reads the first few KB of the file to look for embedded serial strings.
    """
    p = Path(path)
    # Try filename first (fast, no I/O)
    serial = detect_game_serial(str(p))
    if serial:
        return serial

    # Read file content for text-based files
    if p.is_file() and p.stat().st_size < 10 * 1024 * 1024:  # skip >10 MB
        try:
            with open(p, "rb") as f:
                content = f.read(4096)
            serial = detect_game_serial(str(p), content)
            if serial:
                return serial
        except OSError:
            pass

    return ""


def serial_to_display(serial: str) -> str:
    """
    Return a display string for a serial.
    If the serial is in the known-titles map, includes the game title.
    """
    if not serial:
        return ""
    title = _KNOWN_SERIALS.get(serial.upper(), "")
    if title:
        return f"{serial} — {title}"
    return serial


def serial_to_display_with_online_fallback(serial: str, timeout: int = 5) -> str:
    """
    Return a display string for a serial, falling back to an online lookup
    (GameTDB) if the serial is not in the local registry.

    This function may make a network request for unknown serials. Call it
    from a background thread to avoid blocking the UI.

    Returns ``"XXXX-NNNNN — Game Title"`` if a title is found, or just
    the serial if no title is available.
    """
    if not serial:
        return ""
    # Check local registry first (fast path)
    title = _KNOWN_SERIALS.get(serial.upper(), "")
    if title:
        return f"{serial} — {title}"
    # Fallback to online lookup
    from src.core.downloader import lookup_game_title_online
    online_title = lookup_game_title_online(serial, timeout=timeout)
    if online_title:
        return f"{serial} — {online_title}"
    return serial


def normalise_serial(serial: str) -> str:
    """
    Normalise a PS2 serial to ``XXXX-NNNNN`` form (upper-case, dash separator).
    Returns the input unchanged if it doesn't match the expected pattern.
    """
    m = _SERIAL_PATTERN.search(serial)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}"
    return serial.upper()


def lookup_game_title(serial: str) -> str:
    """
    Look up the game title for a given serial from the built-in registry.
    Returns an empty string if the serial is not recognised.
    """
    return _KNOWN_SERIALS.get(serial.upper(), "")


def lookup_game_title_with_online_fallback(serial: str, timeout: int = 5) -> str:
    """
    Look up the game title for *serial*, falling back to an online GameTDB
    lookup if the serial is not in the local registry.

    This function may make a network request for unknown serials. Call it
    from a background thread to avoid blocking the UI.

    Returns the title string, or ``""`` if not found.
    """
    title = _KNOWN_SERIALS.get(serial.upper(), "")
    if title:
        return title
    from src.core.downloader import lookup_game_title_online
    return lookup_game_title_online(serial, timeout=timeout)


def all_known_serials() -> list[tuple[str, str]]:
    """Return a sorted list of (serial, title) tuples from the built-in registry."""
    return sorted(_KNOWN_SERIALS.items(), key=lambda x: x[0])


def detect_serial_from_path(path: str) -> str:
    """
    Scan **every component** of *path* for a PS2 serial.

    This is important for PCSX2's folder-based texture replacement layout::

        textures/SLUS-20062/replacements/some_pack.zip

    Scanning path components means the serial ``SLUS-20062`` is found even
    though the leaf filename is ``some_pack.zip`` (which has no serial in it).

    Returns the first normalised serial found, or ``""`` if none is detected.
    Components are checked from the **deepest** (rightmost) end first so that
    the most specific part of the path takes priority.
    """
    parts = Path(path).parts
    # Iterate from deepest component towards root
    for part in reversed(parts):
        serial = _parse_serial(part)
        if serial:
            return serial
    return ""


def title_to_serials(title_fragment: str) -> List[Tuple[str, str]]:
    """
    Reverse lookup: return all ``(serial, title)`` pairs whose title contains
    *title_fragment* as a case-insensitive substring.

    Also searches game aliases via :class:`~src.core.serial_validator.SerialDatabase`
    so that abbreviations like ``"GoW"`` or ``"DMC3"`` resolve correctly.

    Useful for "find all serials for Kingdom Hearts" style searches.

    Example::

        title_to_serials("kingdom hearts")
        # -> [("SLAJ-25018", "Kingdom Hearts (AS)"),
        #     ("SLKA-25053", "Kingdom Hearts (KR)"), ...]
    """
    if not title_fragment:
        return []
    frag = title_fragment.lower()
    pairs = {
        (serial, title) for serial, title in _KNOWN_SERIALS.items()
        if frag in title.lower()
    }
    # Also resolve via serial DB aliases so abbreviations like "GoW" work.
    try:
        from src.core.serial_validator import SerialDatabase
        _sdb = SerialDatabase()
        seen_titles = {t for _, t in pairs}
        for title in _sdb.search_titles(title_fragment):
            if title not in seen_titles:
                serial = _sdb.get_serial(title)
                if serial:
                    pairs.add((serial, title))
    except Exception:
        pass
    return sorted(pairs, key=lambda x: x[0])


def is_valid_serial(text: str) -> bool:
    """
    Return ``True`` if *text* is a syntactically valid PS2 disc serial.

    A valid serial consists of a recognised 4-letter region prefix followed
    by an optional separator (``-`` or ``_``) and exactly 5 digits.  The
    serial does not need to be present in the built-in titles registry —
    this function validates *format only*, so any real PS2 disc that was
    never added to ``_KNOWN_SERIALS`` is still accepted.

    Examples::

        is_valid_serial("SLUS-20062")  # True  (known title)
        is_valid_serial("SLUS-99999")  # True  (unknown, but valid format)
        is_valid_serial("SLUS_99999")  # True  (underscore separator)
        is_valid_serial("SLUS99999")   # True  (no separator)
        is_valid_serial("XXXX-12345")  # False (unknown prefix)
        is_valid_serial("SLUS-1234")   # False (only 4 digits)
        is_valid_serial("")            # False
    """
    if not text:
        return False
    return bool(_parse_serial(text.strip()))
