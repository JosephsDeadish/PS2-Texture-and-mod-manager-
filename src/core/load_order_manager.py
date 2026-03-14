"""Load Order Manager for PS2 Mod Manager.

Manages the ordered sequence in which texture packs and other mods are
applied for each PS2 game serial.  Like LOOT for Bethesda games, this
module lets users specify the load order of their packs and detects
ordering-sensitive conflicts.

Concepts
--------
Load order matters for texture packs because:

* When two installed packs contain a replacement for the same PCSX2
  texture filename, only one can win.  The pack that is listed *later*
  in the load order takes priority (last-write wins, matching the way
  most mod managers handle layered replacements).
* Packs listed *earlier* provide base content; packs *later* override it.

Example order for a game::

    1. Base Texture Pack        ← lowest priority
    2. HD Environment Pack
    3. Character Pack
    4. UI Overhaul              ← highest priority

If "Base Texture Pack" and "HD Environment Pack" both include a file
called ``grass-abc12345-….png``, the HD Environment Pack version wins
because it is later in the list.

Persistence
-----------
Orders are stored as JSON::

    {
      "version": 1,
      "orders": {
        "SLUS-20062": ["pack-uuid-A", "pack-uuid-B", "pack-uuid-C"],
        "SCUS-97232": ["pack-uuid-D"]
      }
    }

Public API::

    from src.core.load_order_manager import LoadOrderManager

    lom = LoadOrderManager("/path/to/load_order.json")
    lom.set_order("SLUS-20062", ["pack-A", "pack-B", "pack-C"])
    order = lom.get_order("SLUS-20062")
    lom.move_up("SLUS-20062", "pack-B")
    lom.save()
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional


class LoadOrderManager:
    """Manages the load order of mods per game serial.

    Parameters
    ----------
    order_file:
        Path to the JSON persistence file.  Created on first
        :meth:`save`.
    """

    _VERSION = 1

    def __init__(self, order_file: str) -> None:
        self._path = Path(order_file)
        #: serial → ordered list of pack_ids (first = lowest priority)
        self._orders: Dict[str, List[str]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            orders = raw.get("orders", {})
            if isinstance(orders, dict):
                for serial, lst in orders.items():
                    if isinstance(lst, list):
                        self._orders[serial] = [str(x) for x in lst]
        except (json.JSONDecodeError, TypeError):
            pass

    def save(self) -> None:
        """Persist the current load orders to disk atomically."""
        payload = json.dumps(
            {"version": self._VERSION, "orders": self._orders},
            indent=2,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self._path.parent),
            prefix=".loadorder_tmp_",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, str(self._path))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    def get_order(self, serial: str) -> List[str]:
        """Return the current load order for *serial* (copy).

        Items are ordered from **lowest priority** (index 0) to **highest
        priority** (last index).  If no order has been set, returns ``[]``.
        """
        return list(self._orders.get(serial, []))

    def set_order(self, serial: str, order: List[str]) -> None:
        """Replace the load order for *serial* with *order*.

        Duplicate pack IDs in *order* are silently deduplicated while
        preserving the first occurrence.
        """
        seen: set = set()
        deduped: List[str] = []
        for item in order:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        self._orders[serial] = deduped

    def add_pack(self, serial: str, pack_id: str) -> None:
        """Append *pack_id* to the end (highest priority) of *serial*'s order.

        If *pack_id* is already in the list, this is a no-op.
        """
        lst = self._orders.setdefault(serial, [])
        if pack_id not in lst:
            lst.append(pack_id)

    def remove_pack(self, serial: str, pack_id: str) -> bool:
        """Remove *pack_id* from *serial*'s load order.

        Returns
        -------
        bool
            ``True`` if *pack_id* was present and removed.
        """
        lst = self._orders.get(serial, [])
        if pack_id in lst:
            lst.remove(pack_id)
            if not lst:
                del self._orders[serial]
            return True
        return False

    def move_up(self, serial: str, pack_id: str) -> bool:
        """Move *pack_id* one step earlier (lower priority) in the list.

        Returns
        -------
        bool
            ``True`` if the item was moved, ``False`` if it is already at
            the top (index 0) or not present.
        """
        lst = self._orders.get(serial, [])
        if pack_id not in lst:
            return False
        idx = lst.index(pack_id)
        if idx == 0:
            return False
        lst[idx - 1], lst[idx] = lst[idx], lst[idx - 1]
        return True

    def move_down(self, serial: str, pack_id: str) -> bool:
        """Move *pack_id* one step later (higher priority) in the list.

        Returns
        -------
        bool
            ``True`` if the item was moved, ``False`` if it is already at
            the end or not present.
        """
        lst = self._orders.get(serial, [])
        if pack_id not in lst:
            return False
        idx = lst.index(pack_id)
        if idx == len(lst) - 1:
            return False
        lst[idx], lst[idx + 1] = lst[idx + 1], lst[idx]
        return True

    def move_to_top(self, serial: str, pack_id: str) -> bool:
        """Move *pack_id* to the first position (lowest priority).

        Returns ``False`` if *pack_id* is not in the list.
        """
        lst = self._orders.get(serial, [])
        if pack_id not in lst:
            return False
        lst.remove(pack_id)
        lst.insert(0, pack_id)
        return True

    def move_to_bottom(self, serial: str, pack_id: str) -> bool:
        """Move *pack_id* to the last position (highest priority).

        Returns ``False`` if *pack_id* is not in the list.
        """
        lst = self._orders.get(serial, [])
        if pack_id not in lst:
            return False
        lst.remove(pack_id)
        lst.append(pack_id)
        return True

    def set_position(self, serial: str, pack_id: str, position: int) -> bool:
        """Move *pack_id* to the given *position* index (0-based).

        Clamps *position* to valid bounds.  Returns ``False`` if
        *pack_id* is not in the list.
        """
        lst = self._orders.get(serial, [])
        if pack_id not in lst:
            return False
        lst.remove(pack_id)
        position = max(0, min(position, len(lst)))
        lst.insert(position, pack_id)
        return True

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def all_serials(self) -> List[str]:
        """Return all serials that have a configured load order."""
        return list(self._orders.keys())

    def priority(self, serial: str, pack_id: str) -> Optional[int]:
        """Return the 0-based index (priority position) of *pack_id*.

        Higher index = higher priority.  Returns ``None`` if not present.
        """
        lst = self._orders.get(serial, [])
        try:
            return lst.index(pack_id)
        except ValueError:
            return None

    def winner(self, serial: str, pack_ids: List[str]) -> Optional[str]:
        """Given a set of conflicting packs, return the one with highest priority.

        The "winner" is the pack that appears *latest* in the load order
        (last-write-wins semantics).  Packs not in the load order are
        treated as having lower priority than any ordered pack.

        Parameters
        ----------
        serial:
            Game serial whose load order to consult.
        pack_ids:
            IDs of the competing packs.

        Returns
        -------
        str | None
            The winning pack ID, or ``None`` if *pack_ids* is empty.
        """
        if not pack_ids:
            return None
        order = self._orders.get(serial, [])

        def _rank(pid: str) -> int:
            try:
                return order.index(pid)
            except ValueError:
                return -1  # not in load order → lowest priority

        return max(pack_ids, key=_rank)

    def detect_order_conflicts(
        self,
        serial: str,
        texture_id_to_packs: Dict[str, List[str]],
    ) -> List[dict]:
        """Identify textures where the load order determines a winner.

        For each *texture_id* that is claimed by multiple packs, report
        which pack currently wins under the configured load order.

        Parameters
        ----------
        serial:
            Game serial.
        texture_id_to_packs:
            Mapping of texture filename → list of pack IDs that provide it
            (typically derived from :class:`~src.core.texture_hash_db.TextureHashDB`).

        Returns
        -------
        list[dict]
            Each dict has keys:
            ``"texture_id"``, ``"packs"`` (list), ``"winner"`` (str|None).
        """
        results = []
        for tid, packs in sorted(texture_id_to_packs.items()):
            distinct = list(dict.fromkeys(packs))  # deduplicate, preserve order
            if len(distinct) < 2:
                continue
            w = self.winner(serial, distinct)
            results.append({
                "texture_id": tid,
                "packs": distinct,
                "winner": w,
            })
        return results

    def clear_serial(self, serial: str) -> None:
        """Remove all load-order data for *serial*."""
        self._orders.pop(serial, None)

    def clear(self) -> None:
        """Remove all load-order data."""
        self._orders.clear()
