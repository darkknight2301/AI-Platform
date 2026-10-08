"""Discovers characters (folders with manifest.json) and instantiates them."""
from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional

from app.characters.base_character import BaseCharacter, CharacterContext, CharacterInfo

log = logging.getLogger(__name__)


class CharacterLoadError(Exception):
    pass


class CharacterManager:
    def __init__(self, builtin_dir: Path, user_dir: Path, context: CharacterContext,
                 default_id: Callable[[], str]):
        self._dirs = [(Path(builtin_dir), True), (Path(user_dir), False)]
        self._context = context
        self._default_id = default_id
        self._infos: Dict[str, CharacterInfo] = {}
        self._instances: Dict[str, BaseCharacter] = {}
        self._failed: set = set()
        self.discover()

    # ---- discovery ------------------------------------------------------------
    def discover(self) -> List[CharacterInfo]:
        infos: Dict[str, CharacterInfo] = {}
        for directory, builtin in self._dirs:
            if not directory.is_dir():
                continue
            for sub in sorted(p for p in directory.iterdir() if p.is_dir()):
                manifest_path = sub / "manifest.json"
                if not manifest_path.is_file():
                    continue
                try:
                    with open(str(manifest_path), "r", encoding="utf-8") as fh:
                        manifest = json.load(fh)
                    if not isinstance(manifest, dict):
                        raise ValueError("manifest must be an object")
                    cid = str(manifest.get("id") or sub.name)
                    name = str(manifest.get("name") or cid)
                except (ValueError, OSError) as exc:
                    log.warning("Ignoring character folder %s: %s", sub, exc)
                    continue
                if cid in infos:
                    log.info("Character '%s' in %s overrides an earlier one", cid, sub)
                infos[cid] = CharacterInfo(id=cid, name=name, path=sub, manifest=manifest,
                                           builtin=builtin)
        self._infos = infos
        return self.list()

    def list(self) -> List[CharacterInfo]:
        return sorted(self._infos.values(), key=lambda i: (not i.builtin, i.name.lower()))

    def get_info(self, character_id: str) -> Optional[CharacterInfo]:
        return self._infos.get(character_id)

    def resolve_id(self, character_id: str) -> str:
        """Maps ''/unknown ids to the default character."""
        if character_id and character_id in self._infos:
            return character_id
        if character_id:
            log.warning("Unknown character '%s'; using the default", character_id)
        default = self._default_id()
        if default in self._infos:
            return default
        if self._infos:
            return self.list()[0].id
        raise CharacterLoadError("No characters are installed.")

    # ---- instantiation --------------------------------------------------------
    def create(self, character_id: str) -> BaseCharacter:
        cid = self.resolve_id(character_id)
        if cid in self._failed:
            cid = self._fallback_id(cid)
        if cid in self._instances:
            return self._instances[cid]
        try:
            instance = self._build(self._infos[cid])
        except Exception as exc:
            log.exception("Character '%s' failed to load", cid)
            self._failed.add(cid)
            fallback = self._fallback_id(cid)
            if fallback == cid:
                raise CharacterLoadError("Character '%s' failed to load: %s" % (cid, exc))
            return self.create(fallback)
        self._instances[cid] = instance
        return instance

    def _fallback_id(self, failed_id: str) -> str:
        for cid in [self._default_id()] + [i.id for i in self.list()]:
            if cid in self._infos and cid not in self._failed:
                return cid
        return failed_id

    def _build(self, info: CharacterInfo) -> BaseCharacter:
        entry = info.manifest.get("entry")
        if entry:
            path = info.path / str(entry)
            spec = importlib.util.spec_from_file_location("dr_character_%s" % info.id, str(path))
            if spec is None or spec.loader is None:
                raise CharacterLoadError("cannot import %s" % path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            factory = getattr(module, "create_character", None)
            if not callable(factory):
                raise CharacterLoadError("%s has no create_character(info, context)" % path)
            return factory(info, self._context)
        from app.characters.sprite_character import SpriteCharacter   # lazy: needs Qt
        return SpriteCharacter(info, self._context)

    def shutdown(self) -> None:
        for inst in self._instances.values():
            try:
                inst.hide(immediate=True)
            except Exception:
                log.exception("Error hiding character %s", inst.info.id)
