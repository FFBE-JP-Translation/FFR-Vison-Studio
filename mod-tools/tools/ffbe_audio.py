"""Build CRI audio banks and schedule FFBE action and shared casting sounds."""
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import subprocess

import ffrenv
import ffbe_audio_assets

from ffbe_effects.acb_cues import cues, utf
from ffbe_effects.acb_routing import adapt
from ffbe_effects import acb_native, hca_host

ROOT = Path(__file__).resolve().parents[1]
SHELL = "FFRS/Content/Sound/Cri/Se/SE_PP/SE_BTL_PP/SE_BTL_PP"
LB_OPENING_CUE = "se_battle_limitopen_1"
MAGIC_OPENING_CUE = "se_system_magicopen_1"
ABILITY_OPENING_CUE = "se_special_flash_1"


def host_config(skill):
    """Read the installed game's audio settings on first use, including upgrades."""
    path = ROOT / skill.get("audio_config", "extracted/pak/FFRS/Config/DefaultEngine.ini")
    if path.is_file() or skill.get("audio_config"):
        return path
    repak = ROOT / "tools/repak/repak.exe"
    pak = Path(ffrenv.game_paks()) / "FFRS-Windows.pak"
    result = subprocess.run([str(repak), "get", str(pak), "FFRS/Config/DefaultEngine.ini"], capture_output=True)
    if result.returncode:
        raise ValueError("Could not read FFR's audio settings from the installed game")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(result.stdout)
    hca_host.key_from_config(path)
    return path


@lru_cache(maxsize=4)
def bank_info(path, modified):
    data = Path(path).read_bytes()
    if Path(path).suffix == ".json":
        doc = ffbe_audio_assets.read(path)
        digest = hashlib.sha256(data).hexdigest()
        name = "FFBE_SE_" + digest[:12]
        return {"path": str(path), "sha256": digest, "name": name,
                "asset": f"FFRS/Content/Sound/FFBE/{name}",
                "cues": {int(k): v for k, v in doc["cues"].items()}, "audioManifest": doc}
    header = utf(data)[1][0]
    waves = utf(header["WaveformTable"])[1]
    if not header.get("AwbFile") or any(w.get("Streaming") for w in waves):
        raise ValueError("FFBE audio needs a self-contained, non-streaming ACB bank")
    by_id = cues(path)
    cue_rows = utf(header["CueTable"])[1]
    for cue in by_id.values():
        cue["durationMs"] = cue_rows[cue["cueIndex"]]["Length"]
    digest = hashlib.sha256(data).hexdigest()
    name = "FFBE_SE_" + digest[:12]
    return {"path": str(path), "sha256": digest, "name": name,
            "asset": f"FFRS/Content/Sound/FFBE/{name}", "cues": by_id}


@lru_cache(maxsize=128)
def native_selection(path, modified, ids, host_codec):
    """An unsupported cue must not block the other sounds or the unit import."""
    bank = bank_info(path, modified)
    data = Path(path).read_bytes()
    doc = bank.get("audioManifest")
    waves = ffbe_audio_assets.waves(path, doc) if doc else acb_native.awb_files(utf(data)[1][0]["AwbFile"])
    selected, omitted = [], {}
    for cid in ids:
        try:
            cue = bank["cues"][cid]
            if not cue.get("name") or not 0 < cue["durationMs"] < 60000:
                raise ValueError("Missing or unbounded sound cue")
            recordings = [r for r in doc["recordings"] if r["sourceCueId"] == cid] if doc else acb_native.recordings(data, [cid], {cid: cue["name"]})
            if not recordings:
                raise ValueError((doc or {}).get("omitted", {}).get(str(cid), "Missing sound recordings"))
            for rec in recordings:
                if host_codec:
                    hca_host.validate_layout(waves[rec["sourceWaveId"]])
            selected.extend(recordings)
        except (ValueError, KeyError) as ex:
            omitted[cid] = str(ex)
    return selected, omitted


def unavailable_message(omitted):
    return f"FFBE sounds {', '.join(map(str, omitted))} are not supported in this build and will be omitted; other sounds still play."


def warnings(source):
    ids = tuple(sorted({s["cueId"] for s in (source or {}).get("sounds", [])}))
    if not ids:
        return []
    path = attack_bank((source or {}).get("unitId", ""))
    if not path.is_file():
        return ["The FFBE attack sound bank is missing; update the data pack to enable attack sounds."]
    _, omitted = native_selection(str(path.resolve()), path.stat().st_mtime_ns, ids, True)
    return [unavailable_message(omitted)] if omitted else []


def attack_bank(form):
    path = ROOT / "data/ffbe/audio/lb" / (str(form) + ".json")
    return path if path.is_file() else ROOT / "data/ffbe/audio/SE.acb"


def prepare(unit, skill, source, tbl):
    # Native cut-in charge is a distinct sound/pose before the main LB groups.
    # Only profiles with explicit measured/source-backed opening metadata opt in.
    from ffbe_resonance import opening_timing
    opening_phase = opening_timing(source)
    enabled = skill.get("audio") == "native" and skill.get("lb_charge", True) is not False
    if enabled and opening_phase and opening_phase.get("chargeFrame") is not None:
        frame = opening_phase["chargeFrame"] - opening_phase["durationFrames"]
        sounds = list((source or {}).get("sounds", []))
        if not any(s["cueId"] == 647 and s["frame"] == frame for s in sounds):
            sounds.append({"cueId": 647, "frame": frame, "role": "lb_charge"})
        source = {**(source or {}), "sounds": sounds}
    bank, events = _prepare_routed_banks(unit, skill, source, tbl)
    if not enabled:
        return bank, events
    if opening_phase and opening_phase.get("chargeFrame") is not None:
        if not any(e["cueId"] == 647 and e["frame"] == frame for e in events):
            raise ValueError("The prepared FFBE bank is missing the native LB charge sound")
    if any(e["sourceCueName"] == LB_OPENING_CUE for e in events):
        return bank, events
    path = system_bank(skill)
    if path is None:
        print(f"  ! {unit['key']}: System.acb is unavailable; the common LB opening sound is omitted")
        return bank, events
    frame = -opening_phase["durationFrames"] if opening_phase else 0
    opening, extra = prepare_system_cue(unit, skill, path, LB_OPENING_CUE, frame, "lb_opening", tbl)
    return combine(bank, events, opening, extra)


def system_bank(skill):
    """Resolve shared battle sounds independently of a unit's attack bank."""
    explicit = skill.get("audio_system_bank")
    paths = [ROOT / explicit] if explicit else []
    if not explicit:
        if skill.get("audio_bank"):
            paths.append((ROOT / skill["audio_bank"]).with_name("System.acb"))
        paths += [ROOT / "data/ffbe/audio/System.json", ROOT / "data/ffbe/audio/System.acb", Path("S:/FFBE JP Data Export/public/System.acb")]
    path = next((p for p in paths if p.is_file()), None)
    if path is None:
        if explicit:
            raise FileNotFoundError(f"FFBE system sound bank not found: {explicit}")
    return path


def _prepare_routed_banks(unit, skill, source, tbl):
    paths = skill.get('audio_banks')
    if not paths:
        return _prepare_bank(unit, skill, source, tbl)
    result, events = None, []
    routes = {s.get('sourceBank', 'SE') for s in (source or {}).get('sounds', [])}
    if routes - {'SE', 'System'}:
        raise ValueError('Unsupported FFBE source sound bank')
    for route in sorted(routes):
        if route not in paths:
            raise ValueError('Prepared audio manifest missing source bank ' + route)
        selected = [s for s in source['sounds'] if s.get('sourceBank', 'SE') == route]
        bank, extra = _prepare_bank(unit, {**skill, 'audio_bank': paths[route]}, {'sounds': selected}, tbl)
        result, events = combine(result, events, bank, extra)
    return result, events


def prepare_system_cue(unit, skill, path, name, frame, role, tbl):
    info = bank_info(str(path.resolve()), path.stat().st_mtime_ns)
    ids = [cid for cid, cue in info["cues"].items() if cue["name"] == name]
    if len(ids) != 1:
        raise ValueError(f"Expected one {name} cue in {path}")
    return _prepare_bank(unit, {**skill, "audio_bank": str(path.resolve())},
                         {"sounds": [{"frame": frame, "cueId": ids[0], "role": role}]}, tbl)


def combine(bank, events, opening, extra):
    merged = {}
    for item in [*banks(bank), *banks(opening)]:
        merged.setdefault(item['name'], {k:v for k,v in item.items() if k != 'additionalBanks'})
    values = list(merged.values())
    result = {**values[0], 'additionalBanks':values[1:]} if values else None
    return result, sorted(events + extra, key=lambda e: e["frame"])


def prepare_command(unit, skill, source, tbl):
    """Add a shared cast cue only when the action supplies a casting phase.

    ``cast.frame`` is relative to the same action origin as effect-group sounds;
    it may be negative when the magic-idle preparation precedes magic attack.
    Move type/damage type are deliberately not guessed in the audio adapter.
    """
    cast = (source or {}).get("cast")
    if skill.get("audio") != "native" or not cast:
        return _prepare_bank(unit, skill, source, tbl)
    name, frame = cast.get("cueName", MAGIC_OPENING_CUE), cast.get("frame", 0)
    if not isinstance(frame, (int, float)) or isinstance(frame, bool) or not math.isfinite(frame):
        raise ValueError("The casting sound needs a finite source-relative frame")
    if cast.get("bank", "System") == "SE":
        if name != ABILITY_OPENING_CUE:
            raise ValueError(f"Unsupported shared ability casting sound: {name}")
        sounds = list((source or {}).get("sounds", []))
        if not any(s["cueId"] == 100 and s["frame"] == frame for s in sounds):
            sounds.append({"cueId": 100, "frame": frame, "role": "casting"})
        bank, events = _prepare_bank(unit, skill, {**source, "sounds": sounds}, tbl)
        if not any(e["sourceCueName"] == name and e["frame"] == frame for e in events):
            raise ValueError("The prepared FFBE attack bank is missing the requested ability casting sound")
        return bank, sorted(events, key=lambda e: e["frame"])
    if cast.get("bank", "System") != "System":
        raise ValueError("Casting sound bank must be SE or System")
    bank, events = _prepare_bank(unit, skill, source, tbl)
    if any(e["sourceCueName"] == name and e["frame"] == frame for e in events):
        return bank, events
    path = system_bank(skill)
    if path is None:
        raise FileNotFoundError("FFBE System sound bank is required for the requested casting sound")
    opening, extra = prepare_system_cue(unit, skill, path, name, frame, "casting", tbl)
    return combine(bank, events, opening, extra)


def _prepare_bank(unit, skill, source, tbl):
    # The routed original bank produced distorted audio in FFR. "native" tests
    # rebuilt one-shot cues; "experimental" retains the old bank for diagnostics.
    if skill.get("audio") not in ("native", "experimental"):
        return None, []
    if not source or not source.get("sounds"):
        return None, []
    explicit = skill.get("audio_bank")
    paths = [ROOT / explicit] if explicit else [attack_bank(unit.get("ffbe", {}).get("id", "")),
                                               Path("S:/FFBE JP Data Export/public/SE.acb")]
    path = next((p for p in paths if p.is_file()), None)
    if path is None:
        if explicit:
            raise FileNotFoundError(f"FFBE sound bank not found: {explicit}")
        print(f"  ! {unit['key']}: FFBE LB sounds found, but SE.acb is unavailable; set lb_custom.audio_bank")
        return None, []
    bank = bank_info(str(path.resolve()), path.stat().st_mtime_ns)
    if skill.get("audio") == "native":
        waveform_profile = None
        if skill.get("audio_codec") == "host":
            config = host_config(skill)
            waveform_profile = {"revision": 1, "version": 0x300, "key": hca_host.key_from_config(config)}
        selected, omitted = native_selection(str(path.resolve()), path.stat().st_mtime_ns,
                                              tuple(sorted({s["cueId"] for s in source["sounds"]})),
                                              skill.get("audio_codec") == "host")
        if omitted:
            print(f"  ! {unit['key']}: {unavailable_message(omitted)}")
        if not selected:
            return None, []
        signature = json.dumps({"revision": acb_native.REVISION, "source": bank["sha256"],
                                "recordings": selected, "gain": acb_native.DEFAULT_GAIN,
                                "waveformProfile": waveform_profile}, sort_keys=True)
        name = "FFBE_LB_" + hashlib.sha256(signature.encode()).hexdigest()[:12]
        bank = {**bank, "mode": "native", "recordings": selected, "gain": acb_native.DEFAULT_GAIN,
                "name": name, "asset": f"FFRS/Content/Sound/FFBE/{name}", "waveformProfile": waveform_profile}
    events = []
    occurrences = {}
    for sound in source["sounds"]:
        if bank.get("mode") == "native" and sound["cueId"] in omitted:
            continue
        cue = bank["cues"].get(int(sound["cueId"]))
        if cue is None or not cue.get("name") or not 0 < cue["durationMs"] < 60000:
            raise ValueError(f"Missing or unbounded FFBE sound cue {sound['cueId']}")
        name, duration = cue["name"], cue["durationMs"]
        if bank.get("mode") == "native":
            alternatives = [r for r in selected if r["sourceCueId"] == sound["cueId"]]
            count = occurrences.get(sound["cueId"], 0)
            recording = alternatives[count % len(alternatives)]
            occurrences[sound["cueId"]] = count + 1
            name, duration = recording["name"], recording["durationMs"]
        events.append({**sound, "sourceCueName": cue["name"], "cueName": name, "durationMs": duration, "bank": bank["name"]})
    for rel in ("Asset/Sound/DT_SoundCueSheetAsset", "Asset/Sound/CDT_SoundCueSheetAsset_Demo"):
        additions = tbl(rel)["add"]
        if not any(r["row"] == bank["name"] for r in additions):
            additions.append({"row": bank["name"], "cloneFrom": "SE_BTL",
                              "set": {"CueSheetName": bank["name"],
                                      "pCueSheet": bank["asset"].replace("FFRS/Content/", "/Game/")}})
    return bank, events


def banks(bank):
    """All banks referenced by a prepared LB, including shared opening audio."""
    result, seen = [], set()
    def visit(item):
        if not item or id(item) in seen: return
        seen.add(id(item))
        if not any(b['name'] == item['name'] for b in result): result.append(item)
        for child in item.get('additionalBanks', []): visit(child)
    visit(bank)
    return result


def build(bank, out, work, command, usmap, run, legacy):
    patch = Path(work) / (bank["name"] + ".json")
    original = Path(bank["path"]).read_bytes()
    if hashlib.sha256(original).hexdigest() != bank["sha256"]:
        raise ValueError("FFBE sound bank changed after cue lookup")
    # Validate the host profile against its own bank, not FFBE's category IDs.
    native_export = Path(legacy, SHELL + ".uexp").read_bytes()
    native_header = utf(native_export, native_export.index(b"@UTF"))[1][0]
    native_refs = utf(native_header["AcfReferenceTable"])[1]
    if not any(r["Type"] == 3 and r["Name"] == "SE" and r["Id"] == 3 for r in native_refs):
        raise ValueError("FFR sound configuration has an unexpected SE category")
    if not any(r["Type"] == 9 and r["Name"] == "MasterOut" for r in native_refs):
        raise ValueError("FFR sound configuration has no MasterOut bus")
    if bank.get("mode") == "native":
        native_acb = native_export[native_export.index(b"@UTF"):]
        # UAsset exports may have trailing bytes after the ACB's declared size.
        native_acb = native_acb[:int.from_bytes(native_acb[4:8], "big") + 8]
        doc = bank.get("audioManifest")
        raw_waves = ffbe_audio_assets.waves(bank["path"], doc) if doc else None
        routed = acb_native.build(original, native_acb, bank["name"], bank["recordings"], bank["gain"], bank.get("waveformProfile"), raw_waves=raw_waves)
    else:
        routed = adapt(original)
    acb_path = Path(work) / (bank["name"] + ".acb")
    acb_path.write_bytes(routed)
    # Register all cues, preserving the bank's cue indices for CRI lookup APIs.
    cue_info = [{"id": cid, "name": c["name"], "durationMs": c["durationMs"]}
                for cid, c in sorted(bank["cues"].items(), key=lambda p: p[1]["cueIndex"])]
    if bank.get("mode") == "native":
        cue_info = [{"id": i + 1, "name": r["name"], "durationMs": r["durationMs"]}
                    for i, r in enumerate(bank["recordings"])]
    patch.write_text(json.dumps({"legacyRoot": str(legacy), "outRoot": str(out),
                                "atomBanks": [{"from": SHELL, "to": bank["asset"],
                                               "acb": str(acb_path), "sha256": hashlib.sha256(routed).hexdigest(),
                                               "cues": cue_info}]}), encoding="utf-8")
    run([*command, "patch", str(patch), "--usmap", usmap])
