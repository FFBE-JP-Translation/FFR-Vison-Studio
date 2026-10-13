r"""server.py - dev web UI backend for the FFBE -> FF Resonance vision pipeline.

python tools/devui/server.py            -> http://localhost:8765  (serves tools/devui/web/dist + the API)
The spec it edits is mods/EstherTsukiko/units.json (the generator reads the same file); builds run tools/make_vision_mod.py.
"""
import io, json, os, re, subprocess, sys, threading, time, uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, os.path.join(ROOT, "tools", "ffbe2ss6"))
import ffr_catalog, ffbe_catalog, build_icons
import dump_ffbe_unit, ffrenv, ffbe_resonance
import unit_downloads, custom_units

MOD = os.path.join(ROOT, "mods", "EstherTsukiko")
SPEC = os.environ.get('FFR_UNIT_SPEC') or os.path.join(MOD, "units.json")
LAYOUT = os.path.join(MOD, "icon_layout.json")
BUILD = os.path.join(ROOT, "build", "devui")
PREVIEWS = os.path.join(BUILD, "preview")
USMAP = ffrenv.USMAP
LEGACY = os.path.join(ROOT, "extracted", "legacy")
GAME_EXE = ffrenv.GAME_EXE
def game_paks():
    """<game>/FFRS/Content/Paks, or None until the game folder is known (see tools/devui/setup.py)"""
    try: return ffrenv.game_paks()
    except FileNotFoundError: return None
FIRST_VISION_ID = 13500   # leaves room for the full game's own visions (the demo stops at 13130)

ENGINE_VERSION = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip() if os.path.exists(os.path.join(ROOT, "VERSION")) else "dev"
app = FastAPI(title="ffr devui")
from vision_card_routes import router as vision_card_router
app.include_router(vision_card_router)
state = {"running": False, "log": [], "result": None, "started": None}

def load_spec():
    if not os.path.exists(SPEC): return []
    with open(SPEC, encoding="utf-8") as file:
        return [ffbe_resonance.migrate_cg(u) for u in json.load(file)]

def save_spec(units):
    os.makedirs(os.path.dirname(SPEC), exist_ok=True)
    units = [ffbe_resonance.migrate_cg(u) for u in units]
    json.dump(units, open(SPEC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def load_layout():
    if os.path.exists(LAYOUT):
        lay = json.load(open(LAYOUT, encoding="utf-8"))
        return {k: {**build_icons.DEFAULT_LAYOUT[k], **(lay.get(k) or {})} for k in build_icons.DEFAULT_LAYOUT}
    return json.loads(json.dumps(build_icons.DEFAULT_LAYOUT))

def game_running():
    return ffrenv.game_running()

def run_tool(args):
    return subprocess.run(ffrenv.FFRDT + args + ["--usmap", USMAP], capture_output=True, text=True, env=dict(os.environ, MSYS_NO_PATHCONV="1"))

# ---------------------------------------------------------------- catalogues
@app.get("/api/ffr/catalog")
def ffr_cat(): return ffr_catalog.load()

@app.post("/api/ffr/catalog/rebuild")
def ffr_rebuild(): ffr_catalog.build(); return {"ok": True}

@app.get("/api/ffr/icon/{name}")
def ffr_icon(name: str):
    if name.startswith('ffbe_'):
        import skill_icons
        p = skill_icons.path(name[5:])
        if not p: raise HTTPException(404)
        return FileResponse(p, media_type='image/png')
    p = os.path.join(BUILD, "icons", os.path.basename(name))
    if not p.endswith(".png"): p += ".png"
    if not os.path.exists(p): raise HTTPException(404)
    return FileResponse(p, media_type="image/png")

@app.get("/api/ffbe/units")
def ffbe_units(): return ffbe_catalog.load_index()

@app.post("/api/ffbe/units/rebuild")
def ffbe_rebuild(): return ffbe_catalog.build_index()

@app.get("/api/ffbe/unit/{uid}")
def ffbe_unit(uid: str):
    d = ffbe_catalog.unit_detail(uid)
    if not d:
        row = ffbe_catalog.index_rows().get(uid)
        if row and row.get('previewDetail'):
            d = {**row['previewDetail'], 'previewOnly': True, 'abilities': [], 'passives': [], 'skills': [], 'roles': row.get('roles', [])}
            d['forms'] = {fid: {**form, 'sprites': [], 'available': fid in row.get('spriteForms', [])} for fid, form in d.get('forms', {}).items()}
    if not d: raise HTTPException(404, "unit not in the FFBE data")
    row = ffbe_catalog.index_rows().get(uid) or {}
    for fid, form in d.get('forms', {}).items():
        form['available'] = bool(form.get('sprites')) or fid in row.get('spriteForms', [])
    return d


@app.get('/api/ffbe/idle/{form}.webp')
def idle_preview(form: str):
    path = unit_downloads.preview_file(form, 'idle')
    if path: return FileResponse(path, media_type='image/webp')
    return ffbe_anim_webp(form, 'idle')


asset_jobs = {}
asset_jobs_lock = threading.Lock()


@app.get('/api/assets/catalog')
def local_asset_catalog(req: Request):
    import converted_units
    return converted_units.overlay({}, str(req.base_url))


@app.get('/api/assets/converted/{form}')
def converted_archive(form: str):
    import converted_units
    try:
        path = converted_units.archive(form)
    except (OSError, ValueError) as ex:
        raise HTTPException(404, str(ex))
    return FileResponse(path, media_type='application/octet-stream', filename=form + '.ffr')


@app.post('/api/assets/prepare')
async def prepare_assets(req: Request):
    body = await req.json()
    uid, form = str(body.get('ffbeId', '')), str(body.get('form', ''))
    if not uid.isdigit() or not form.isdigit(): raise HTTPException(422, 'Choose a unit and look first.')
    with asset_jobs_lock:
        for job, status in asset_jobs.items():
            if status['uid'] == uid and status['form'] == form and status['state'] == 'running': return {'job': job}
        for job in list(asset_jobs)[:-32]:
            if asset_jobs[job]['state'] != 'running': del asset_jobs[job]
        job = uuid.uuid4().hex
        status = {'uid': uid, 'form': form, 'state': 'running', 'stage': 'Preparing unit', 'received': 0, 'total': 0}
        asset_jobs[job] = status
    def work():
        try:
            unit_downloads.ensure_selection(uid, form, lambda **kw: status.update(kw))
            status.update(state='done', stage='Ready')
        except Exception as ex:
            status.update(state='failed', error=str(ex))
    threading.Thread(target=work, daemon=True).start()
    return {'job': job}


@app.get('/api/assets/blobs/{prefix}/{digest}')
def shared_effect_blob(prefix: str, digest: str):
    import converted_units
    try: path = converted_units.blob(prefix, digest)
    except (OSError, ValueError) as ex: raise HTTPException(404, str(ex))
    return FileResponse(path, media_type='application/octet-stream')


@app.get('/api/assets/prepare/{job}')
def assets_progress(job: str):
    if job not in asset_jobs: raise HTTPException(404, 'This download is no longer active. Retry Add unit.')
    return dict(asset_jobs[job])


@app.get('/api/custom/template/{kind}')
def custom_template(kind: str):
    if kind not in ('unit', 'animations'): raise HTTPException(404)
    data = custom_units.UNIT_TEMPLATE if kind == 'unit' else custom_units.ANIMATION_TEMPLATE
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="{kind}.json"'})


@app.post('/api/spec/custom')
async def add_custom_unit(req: Request):
    if state['running']: raise HTTPException(409, 'Wait for the current build to finish before importing a unit.')
    if int(req.headers.get('content-length', 0)) > 48 * 1024 * 1024: raise HTTPException(413, 'The import exceeds 48 MiB.')
    chunks = []; size = 0
    async for chunk in req.stream():
        size += len(chunk)
        if size > 48 * 1024 * 1024: raise HTTPException(413, 'The import exceeds 48 MiB.')
        chunks.append(chunk)
    try:
        body = json.loads(b''.join(chunks))
        if not isinstance(body, dict): raise ValueError('An import object is required.')
        units = load_spec()
        spec, warnings, dest = custom_units.prepare(body, units, ffr_catalog.load(), default_spec)
        try:
            units.append(spec); save_spec(units)
        except BaseException:
            import shutil
            shutil.rmtree(dest)
            raise
        return {'unit': spec, 'warnings': warnings}
    except (ValueError, KeyError, TypeError) as ex:
        raise HTTPException(422, str(ex))

@app.get("/api/ffbe/icon/{form}")
def ffbe_icon(form: str):
    p = ffbe_catalog.icon_png(re.sub(r"\D", "", form))
    if not p: raise HTTPException(404)
    return FileResponse(p, media_type="image/png")


@app.get("/api/ffbe/lb/{form}")
def ffbe_lb_profile(form: str, lb_id: str | None = None, source: str = "JP"):
    import ffbe_lb
    try:
        custom = next((u for u in load_spec() if u.get('custom') and u.get('ffbe', {}).get('id') == form), None)
        unit = custom or {"ffbe": {"id": form, "source": source}}
        skill = dict(custom.get('lb_custom') or {}) if custom else {}
        if lb_id: skill['ffbe_lb_id'] = lb_id
        data, result = ffbe_lb.resolve_import(unit, skill)
        result["variants"] = []
        for lid in (data or {}).get("availableLbIds", []):
            variant, _ = ffbe_lb.resolve_import(unit, {**skill, "ffbe_lb_id": lid})
            if variant:
                result["variants"].append({"id": lid, "name": variant["name"], "elements": variant.get("elements", [])})
        import ffbe_audio
        result["warnings"] = result.get("warnings", []) + (data or {}).get("warnings", []) + ffbe_audio.warnings(data)
        return result
    except ValueError as ex:
        raise HTTPException(422, str(ex))

@app.get("/api/ffbe/abilityicon/{name}")
def ffbe_ability_icon(name: str):
    p = ffbe_catalog.ability_icon_path(os.path.basename(name))
    if not p: raise HTTPException(404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "max-age=86400"})

@app.post('/api/ffbe/lb/preview')
async def reviewed_lb_preview(req: Request):
    import ffbe_lb
    body = await req.json()
    try:
        _, result = await run_in_threadpool(ffbe_lb.resolve_import, body['unit'], body['unit']['lb_custom'])
        return result
    except (ValueError, KeyError, TypeError) as ex:
        raise HTTPException(422, str(ex)) from ex

@app.get("/api/ffbe/anims/{form}")
def ffbe_anims(form: str):
    form = re.sub(r"\D", "", form)
    if not ffbe_catalog.sprite_dir(form): raise HTTPException(404, "no sprites for this form")
    return {"form": form, "anims": ffbe_catalog.anims_for(form)}

@app.get("/api/ffbe/motion/{form}/{anim}")
def ffbe_motion(form: str, anim: str):
    form = re.sub(r"\D", "", form); anim = re.sub(r"[^a-z_0-9]", "", anim)
    s = ffbe_catalog.motion_seconds(form, anim)
    if s is None: raise HTTPException(404, "no such motion")
    return {"form": form, "anim": anim, "seconds": round(s, 2)}

@app.get("/api/ffbe/anim/{form}/{anim}.webp")
def ffbe_anim_webp(form: str, anim: str):
    from ffbe_frames import RENDER_VERSION
    form = re.sub(r"\D", "", form); anim = re.sub(r"[^a-z_0-9]", "", anim)
    os.makedirs(PREVIEWS, exist_ok=True)
    p = os.path.join(PREVIEWS, f"{form}_{anim}_r{RENDER_VERSION}.webp")
    if not os.path.exists(p):
        try: open(p, "wb").write(ffbe_catalog.render_webp(form, anim))
        except FileNotFoundError: raise HTTPException(404, "no such animation")
    return FileResponse(p, media_type="image/webp", headers={"Cache-Control": "no-cache"})

@app.get("/api/ffbe/preview/{form}/{anim}")
def ffbe_preview(form: str, anim: str):
    from ffbe_frames import RENDER_VERSION
    form = re.sub(r"\D", "", form); anim = re.sub(r"[^a-z_0-9]", "", anim)
    os.makedirs(PREVIEWS, exist_ok=True)
    p = os.path.join(PREVIEWS, f"{form}_{anim}_r{RENDER_VERSION}.png")
    if not os.path.exists(p):
        try: open(p, "wb").write(ffbe_catalog.render_apng(form, anim))
        except FileNotFoundError: raise HTTPException(404, "no such animation")
    return FileResponse(p, media_type="image/apng")

# ---------------------------------------------------------------- spec
@app.get("/api/spec")
def get_spec(): return load_spec()

@app.put("/api/spec")
async def put_spec(req: Request):
    units = await req.json()
    if not isinstance(units, list): raise HTTPException(400, "list expected")
    save_spec(units); return {"ok": True, "count": len(units)}

def slug(name):
    s = re.sub(r"[^a-z0-9]+", "", (name or "unit").lower().replace("(khiii)", ""))
    return s or "unit"

ROLE_MAP = [("break", "eUnitRole::Breaker"), ("heal", "eUnitRole::Healer"), ("support", "eUnitRole::Enhancer"), ("buff", "eUnitRole::Enhancer"),
            ("debuff", "eUnitRole::Jammer"), ("jam", "eUnitRole::Jammer"), ("tank", "eUnitRole::Defender"), ("defend", "eUnitRole::Defender"),
            ("attack", "eUnitRole::Attacker"), ("damage", "eUnitRole::Attacker"), ("mage", "eUnitRole::Attacker")]
HEAL_WORDS = ("heal", "restore", "hp (", "increase atk", "increase def", "increase mag", "increase spr", "mitigat", "protect", "regen", "lb gauge", "raise")
SYNCHRO_DEFAULT = [[], [["BaseParameter", 1, 50]], [["BaseParameter", 5, 5]], [["BaseParameter", 6, 5]], [["BaseParameter", 2, 10]],
                   [["BaseParameter", 7, 5]], [["BaseParameter", 8, 5]], [["BaseParameter", 9, 3]], [["BaseParameter", 1, 50]], [["BaseParameter", 5, 8], ["BaseParameter", 11, 8]]]

def default_spec(detail, form, key, name, units):
    ids = [u["id"] for u in units if u["id"] >= FIRST_VISION_ID] + [FIRST_VISION_ID - 1]
    vid = max(ids) + 1; n = vid - FIRST_VISION_ID
    roles = []
    for r in detail.get("roles") or []:
        for kw, role in ROLE_MAP:
            if kw in str(r).lower() and role not in roles: roles.append(role)
    if not roles: roles = ["eUnitRole::Attacker"]
    sm = detail.get("statsMax") or {}
    magic = any("mag" in str(r).lower() for r in detail.get("roles") or []) or (sm.get("MAG", 0) > sm.get("ATK", 0) * 1.1)
    lb = (detail["forms"].get(form) or {}).get("limitburst") or (detail["forms"].get(detail.get("maxForm")) or {}).get("limitburst") or {}
    lb_text = " ".join(lb.get("effects") or []).lower()
    supportive = bool(lb_text) and any(w in lb_text for w in HEAL_WORDS) and "damage" not in lb_text
    lb_name = lb.get("name") or f"{name}'s Resonance"
    desc = detail.get("description") or f"A vision of {name}, ported from Final Fantasy Brave Exvius."
    spec = {
        "key": key, "jp": detail.get("jpname") or name, "en": name, "id": vid, "sort": vid + 70,
        "desc": desc,
        "donor": 13108 if magic else 13125,
        "ffbe": {"dir": f"units/ffbe/{key}/sprites/{form}", "id": form, "source": detail.get("region", "GL"), "base": detail["id"]},
        "attackType": "Magic" if magic else "Physic", "roles": roles,
        "stats": detail.get("ffrStats") or ffbe_catalog.ffr_stats(sm), "elemRes": {},
        "command": {"id": 320 + n, "en": f"{name}'s Skills", "desc": f"Skills unique to {name}."},
        "master": {"id": vid * 100, "en": f"Spirit of {name}", "desc": f"{name}'s resonance flows into the wearer."},
        "price": 1, "menuScale": 2.52, "icon": {"style": "border", "rarity": str(detail.get("rarity", [None, 7])[1] or 7)},
        "lb": 440090,
        "lb_custom": {"from": 414100 if supportive else 440110, "presentation": "ffbe", "field_color_mode": "element", "audio": "native", "audio_codec": "host",
                      "visuals": 414100 if supportive else 440110, "target_effect": None,
                      "clone_sequence": True, "mute": ["VO_"], "caption_from": 440240 if supportive else 440260,
                      "jp": f"{detail.get('jpname') or name}_LB", "en": lb_name, "nameAuto": True, "desc": " ".join(lb.get("effects") or []) or f"{name}'s Resonance.",
                      "set": {} if supportive else {"element": "None"},
                      "sequence_edits": {},
                      "effect_swaps": []},
        "skills": {}, "awakening": [[], [], [], []], "synchro": [list(map(list, lv)) for lv in SYNCHRO_DEFAULT],
        "ffbeMap": {"skills": {}, "passives": {}},
    }
    spec["synchro"][9].append(["MasterSkill", spec["master"]["id"]])
    import ffbe_lb
    lb_source, resolved = ffbe_lb.resolve_import(spec, spec["lb_custom"])
    source_name = (lb_source or {}).get("name")
    if source_name and not ffbe_catalog.is_jp(source_name):
        spec["lb_custom"]["en"] = source_name
    spec["lb_custom"]["mechanics"] = "ffbe"
    if resolved["supported"]:
        spec["lb_custom"].update({"set": resolved["set"], "desc": resolved["description"], "descAuto": True,
                                  "ffbe_lb_id": resolved["lbId"]})
    if os.environ.get("FFR_LOCAL_RESONANCE_TEST") == "1" or os.environ.get('FFR_CONVERTED_UNITS'):
        # The private test launcher grants this shortcut for repeated LBs.
        # Public imports never enable the environment flag.
        move = next(s for s in ffr_catalog.STUDIO_SKILLS if s["key"] == "raegen_blast")
        sid = 445000 + (vid - 13100) * 100
        spec["skills"][str(sid)] = {**json.loads(json.dumps(move["recipe"])),
                                  "jp": name + "_Raegen Blast", "en": move["name"],
                                  "desc": move["desc"], "descAuto": False, "studio": move["key"]}
        spec["awakening"][0].append(["ActiveSkill", sid])
        spec.update(testingMPCost=1, presentationStep='target_camera')
        spec['skills'][str(sid)].setdefault('set', {})['Cost'] = 1
    return spec

@app.post("/api/spec/add")
async def add_unit(req: Request):
    body = await req.json()
    uid = str(body.get("ffbeId") or "")
    requested_form = str(body.get('form') or '')
    if requested_form:
        try: await run_in_threadpool(unit_downloads.ensure_selection, uid, requested_form)
        except ValueError as ex: raise HTTPException(422, str(ex))
    detail = ffbe_catalog.unit_detail(uid)
    if not detail: raise HTTPException(404, "unit not in the FFBE data")
    form = str(body.get("form") or detail.get("maxForm") or uid)
    name = body.get("name") or detail.get("name")
    units = load_spec()
    key = body.get("key") or slug(name)
    if any(u["key"] == key for u in units): raise HTTPException(400, f"{name} is already in the mod")
    spec = default_spec(detail, form, key, name, units)
    sh = ffbe_catalog.shift_info(form)
    extra = []
    if sh:
        spec["ffbe"]["baseForm"] = sh["base"]; spec["ffbe"]["baseDir"] = f"units/ffbe/{key}/sprites/{sh['base']}"; spec["ffbe"]["shift"] = sh["kind"]
    row = ffbe_catalog.index_rows().get(uid) or {}
    if row.get("pairOf"): extra.append(row["pairOf"])
    extra += [m for m in (row.get("mergedIds") or []) if m not in extra]   # one row per character: the folded ids' forms are looks too
    wanted = [f for f in ([form] + list(row.get("spriteForms") or [])) if f]      # the chosen look first: its sheets must be copied
    try:
        dump_ffbe_unit.dump(uid, key, extra, detail.get("region"), forms=wanted)
    except Exception as ex:
        raise HTTPException(500, f"FFBE dump failed: {ex}")
    if not spec.get('custom'):
        # New visions start with their strongest compatible native kit spread
        # over all four awakening levels. Opening an existing vision only
        # hydrates its library, preserving the user's authored loadout.
        import vision_import
        try:
            await run_in_threadpool(vision_import.hydrate, spec)
            await run_in_threadpool(vision_import.initialize_native_loadout, spec)
            if os.environ.get('FFR_CONVERTED_UNITS'):
                import ffbe_presentation
                prepared = ffbe_presentation.BUNDLES / (form + '.json')
                moves = json.loads(prepared.read_text(encoding='utf-8'))['moves'] if prepared.is_file() else {}
                # A newly added test unit's default LB has no source snapshot.
                # Bind its prepared native LB so it can resolve the effects.
                lb = next((e for e in spec['ffbeLibrary'] if e['kind'] == 'LB'
                           and e['status'] == 'ready' and e['sourceKey'] in moves), None)
                if lb:
                    await run_in_threadpool(vision_import.equip, spec, lb['sourceKey'])
        except (ValueError, KeyError, TypeError) as ex:
            raise HTTPException(422, str(ex)) from ex
    elif body.get("autoport", True):
        import autoport
        autoport.autoport(spec, ffr_catalog.load(), detail)
    units.append(spec); save_spec(units)
    return spec

@app.post("/api/spec/{key}/autoport")
def autoport_unit(key: str):
    import autoport
    units = load_spec(); u = next((u for u in units if u["key"] == key), None)
    if not u: raise HTTPException(404)
    autoport.autoport(u, ffr_catalog.load()); save_spec(units)
    return u

@app.delete("/api/spec/{key}")
def del_unit(key: str):
    units = load_spec(); units = [u for u in units if u["key"] != key]; save_spec(units); return {"ok": True}


@app.post("/api/ffbe/ability/import")
async def import_ability(req: Request):
    """Return an edited draft using structured mechanics, without saving it."""
    from copy import deepcopy
    import autoport
    body = await req.json()
    try:
        unit = deepcopy(body["unit"])
        review = await run_in_threadpool(autoport.import_entry, unit, body["ability"], body.get("region"), choices=body.get("effectChoices"))
        unit["conversionReview"] = [r for r in unit.get("conversionReview", [])
            if (str(r.get("id")),r.get("kind")) != (str(body["ability"]["id"]),body["ability"].get("kind"))]
        if review:
            unit["conversionReview"].append(review)
        return unit
    except (ValueError, TypeError, KeyError) as ex:
        raise HTTPException(422, str(ex)) from ex

@app.post("/api/ffbe/kit/preview")
async def preview_kit(req: Request):
    import autoport
    body = await req.json()
    try:
        return await run_in_threadpool(autoport.preview_kit, body["unit"])
    except (ValueError, TypeError, KeyError) as ex:
        raise HTTPException(422, str(ex)) from ex

@app.post("/api/ffbe/kit/import")
async def import_kit(req: Request):
    from copy import deepcopy
    import autoport
    body = await req.json()
    try:
        return await run_in_threadpool(autoport.autoport, deepcopy(body["unit"]))
    except (ValueError, TypeError, KeyError) as ex:
        raise HTTPException(422, str(ex)) from ex

# ---------------------------------------------------------------- icons (layout shared by every unit)
@app.post('/api/ffbe/kit/loadout')
async def kit_loadout(req: Request):
    from copy import deepcopy
    import vision_import
    body = await req.json()
    unit = deepcopy(body['unit'])
    try:
        if body.get('remove'):
            found = vision_import.imported(unit, body['sourceKey'])
            if found is None: raise ValueError('This ability is not equipped')
            vision_import.remove(unit, *found)
        else:
            await run_in_threadpool(vision_import.equip, unit, body['sourceKey'], body.get('replaceId'))
        return unit
    except (ValueError, KeyError, TypeError) as ex:
        raise HTTPException(422, str(ex)) from ex

@app.post('/api/studio/grants')
async def studio_grants(req: Request):
    from copy import deepcopy
    from studio_grants import action
    body = await req.json()
    try:
        return await run_in_threadpool(action, deepcopy(body['unit']), body)
    except (ValueError, KeyError, TypeError, IndexError) as ex:
        raise HTTPException(422, str(ex)) from ex

@app.get("/api/layout")
def get_layout(): return load_layout()

@app.put("/api/layout")
async def put_layout(req: Request):
    lay = await req.json()
    json.dump(lay, open(LAYOUT, "w", encoding="utf-8"), indent=1); return {"ok": True}

def unit_icon_image(u):
    if not u or not u.get("ffbe"): raise HTTPException(404)
    p = os.path.join(ROOT, u["ffbe"]["dir"], f"unit_icon_{u['ffbe']['id']}.png")
    if not os.path.exists(p): raise HTTPException(404, "no unit_icon for this form")
    return Image.open(p)

@app.get("/api/ffbe/effects/{kind}/{sid}")
def ffbe_effects(kind: str, sid: str):
    """effect groups (files, offsets, sound cue ids) an FFBE ability / magic / limit burst plays, from the live tables"""
    require_effect_authoring()
    sys.path.insert(0, os.path.join(ROOT, "tools", "ffbe_effects"))
    import catalog as fxcat
    try:
        d = fxcat.skill_effects(kind, sid)
    except Exception as ex:
        raise HTTPException(500, f"effect lookup failed: {ex}")
    if not d: raise HTTPException(404, "no FFBE row")
    return d

# ---------------------------------------------------------------- Brave Exvius animation preview (unit motion + converted effect layers)
preview_jobs = {}

def require_effect_authoring():
    if not os.path.isfile(os.path.join(ROOT, 'tools', 'ffbe_effects', 'catalog.py')):
        raise HTTPException(409, 'Effects are prepared offline and supplied with unit packs. Import an updated unit pack to use its effects.')

@app.get("/api/ffbe/effects/layers/{kind}/{sid}")
def ffbe_effect_layers(kind: str, sid: str):
    """default effect layers (source file, anchor, layer, time, offset) for an ability / magic / limit burst, as auto-port would pick them"""
    require_effect_authoring()
    import autoport
    sys.path.insert(0, os.path.join(ROOT, "tools", "ffbe_effects")); import catalog as fxcat
    info = fxcat.skill_effects(kind, sid)
    if not info: raise HTTPException(404, "no FFBE row")
    fake = {"key": "preview", "portEffects": True}
    ab = {"id": sid, "kind": "MAGIC" if kind == "magic" else ("LB" if kind == "lb" else "ABILITY"), "name": info.get("name")}
    entries = autoport.ffbe_effect_entries(fake, ab, 0, kind_override=kind)
    for e in entries:
        e["anchorFfbe"] = e.get("anchor")   # 1 each target / 2 target group / 3 caster (catalog.py)
        e["anchor"] = "target" if e.get("at_target") else "caster"
        e["layer"] = "back" if e["offset"][0] > 0 else "front"
        e["offsetXY"] = [e["offset"][1], e["offset"][2]]
    return {"name": info.get("name"), "groups": info.get("groups"), "layers": entries}

@app.post("/api/ffbe/effects/preview")
async def ffbe_effect_preview(req: Request):
    require_effect_authoring()
    body = await req.json()
    import uuid
    job = uuid.uuid4().hex[:10]; preview_jobs[job] = {"state": "rendering", "log": [], "file": None}
    def work():
        try:
            sys.path.insert(0, os.path.join(ROOT, "tools", "ffbe_effects")); import preview_anim
            layers = []
            for e in body.get("layers", []):
                ly = {"name": e.get("name"), "source": e.get("source"), "anchor": e.get("anchor", "caster"), "layer": e.get("layer", "front"),
                      "time": float(e.get("time", 0)), "offset": e.get("offsetXY") or [0, 0], "scale": float(e.get("scale", 1.0)), "add_gain": float(e.get("add_gain", 1.0))}
                for k in ("repeat", "interval", "exclude", "max_units", "particles", "max_frames", "compose", "min_frames"):   # bake options, see tools/ffbe_effects/layer_spec.py
                    if e.get(k) not in (None, "", []): ly[k] = e[k]
                layers.append(ly)
            ref = {"kind": body.get("kind"), "sid": str(body.get("sid"))} if body.get("kind") and body.get("sid") else None
            png = preview_anim.render_preview(str(body["form"]), body.get("anim") or "idle", layers, seconds=float(body.get("seconds", 4)),
                                              log=lambda m: preview_jobs[job]["log"].append(str(m)), mode=body.get("mode") or "ffr", ref=ref)
            os.makedirs(os.path.join(ROOT, "build", "effects", "preview"), exist_ok=True)
            fp = os.path.join(ROOT, "build", "effects", "preview", job + ".png"); open(fp, "wb").write(png)
            preview_jobs[job].update({"state": "done", "file": fp})
        except Exception as ex:
            preview_jobs[job].update({"state": "error", "error": str(ex)})
    threading.Thread(target=work, daemon=True).start()
    return {"job": job}

@app.get("/api/ffbe/effects/preview/{job}/state")
def ffbe_effect_preview_state(job: str):
    j = preview_jobs.get(job)
    if not j: raise HTTPException(404)
    return {"state": j["state"], "log": j["log"][-5:], "error": j.get("error")}

@app.get("/api/ffbe/effects/preview/{job}/image")
def ffbe_effect_preview_image(job: str):
    j = preview_jobs.get(job)
    if not j or not j.get("file"): raise HTTPException(404)
    return FileResponse(j["file"], media_type="image/png", headers={"Cache-Control": "no-cache"})

@app.get("/api/spec/{key}/icon/{kind}")
def spec_icon(key: str, kind: str, l: str = None, style: str = None, rarity: str = None):
    """icon preview (face / timeline / ability) rendered live from the unit's spec; l = JSON layout override (Icon frames page),
    style / rarity = unsaved dropdown values from the Profile tab so the preview follows them before Save"""
    u = next((u for u in load_spec() if u["key"] == key), None)
    ic = (u or {}).get("icon") or {}
    layout = json.loads(l) if l else load_layout()
    size = 64 if kind == "ability" else 128
    if kind not in ("face", "timeline", "ability"): raise HTTPException(404)
    img = build_icons.render(kind, unit_icon_image(u), size, style or ic.get("style", "border"), str(rarity or ic.get("rarity", "7")), layout)
    buf = io.BytesIO(); img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-cache"})

# ---------------------------------------------------------------- sequences (Resonance / skill templates)
def flat(o, pre=""):
    out = {}
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "$struct": continue
            out.update(flat(v, pre + k + "."))
    elif isinstance(o, list):
        for i, v in enumerate(o): out.update(flat(v, pre[:-1] + f"[{i}]."))
    else: out[pre[:-1]] = o
    return out

def package_json(uasset, kind):
    """cached ffr-dt tojson / seqdump of a legacy package"""
    base = os.path.join(BUILD, "seqjson", os.path.basename(uasset)[:-7])
    os.makedirs(os.path.dirname(base), exist_ok=True)
    out = base + ("." + kind + ".json")
    if not os.path.exists(out):
        r = run_tool([kind, uasset, out])
        if r.returncode != 0: return None
    return json.load(open(out, encoding="utf-8"))

def first_int(o):
    """dig through nested {"Value": ...} wrappers (FrameNumber structs etc.) to the number"""
    for _ in range(8):
        if isinstance(o, (int, float)) and not isinstance(o, bool): return o
        if isinstance(o, dict): o = o.get("Value")
        elif isinstance(o, list) and o: o = o[0]
        else: return None
    return None

def key_times(tj):
    """event function export index -> (ticks, track disabled) from a sequence package's tojson"""
    ex = tj["Exports"]; imps = tj["Imports"]
    def cls(e): i = e.get("ClassIndex"); return imps[-i - 1]["ObjectName"] if isinstance(i, int) and i < 0 else ex[i - 1]["ObjectName"] if isinstance(i, int) and i > 0 else "?"
    def prop(e, n): return next((p for p in e.get("Data", []) if p.get("Name") == n), None)
    times = {}
    for e in ex:
        if cls(e) != "MovieSceneEventTrack": continue
        dis = prop(e, "bIsEvalDisabled"); dis = bool(dis["Value"]) if dis else False
        secs = prop(e, "Sections")
        for sref in (secs["Value"] if secs else []):
            si = sref["Value"] if isinstance(sref, dict) else sref
            if not isinstance(si, int) or si <= 0 or si > len(ex): continue          # imported / missing section
            ch = prop(ex[si - 1], "EventChannel")
            if not ch: continue
            kv = next((v for v in ch["Value"] if isinstance(v, dict) and v.get("Name") == "KeyValues"), None); kt = next((v for v in ch["Value"] if isinstance(v, dict) and v.get("Name") == "KeyTimes"), None)
            for i, key in enumerate(kv["Value"] if kv else []):
                ptrs = next((v for v in key["Value"] if isinstance(v, dict) and v.get("Name") == "Ptrs"), None)
                fn = next((v for v in ptrs["Value"] if isinstance(v, dict) and v.get("Name") == "Function"), None) if ptrs else None
                t = first_int(kt["Value"][i]) if kt and i < len(kt["Value"]) else None
                if fn: times[fn["Value"]] = (t, dis)
    return times

@app.get("/api/seq/{skill_id}")
def seq_events(skill_id: int):
    """storyboard of a skill's battle sequence: motions, effect spawns, colours, tints, sounds with their times"""
    cat = ffr_catalog.load()
    sk = next((s for s in cat["skills"] if s["id"] == skill_id), None)
    if not sk or not sk["seqPath"]: raise HTTPException(404, "no sequence")
    folder = sk["seqPath"].split("/Game/")[1].rsplit("/", 1)[0]
    legacy_dir = os.path.join(LEGACY, "FFRS", "Content", folder)
    if not os.path.exists(os.path.join(legacy_dir, sk["seqPath"].rsplit("/", 1)[1] + ".uasset")):
        subprocess.run(ffrenv.py(os.path.join(ROOT, "tools", "extract_legacy.py"), "--filter", folder), capture_output=True, text=True)
    KEEP = {"UnitPlayAnimByName": ("Unit_PlayAnimByName_AnimationName", "Unit_PlayAnimByName_InLoopCount", "Unit_PlayAnimByName_InPlayRate"),
            "EffectSpawnNiagaraAtRandom": ("Effect_NiagaraData.niagaraAsset", "Effect_NiagaraData.PartName", "Effect_SpawnNiagara_bAllFriends", "Effect_SpawnNiagara_bAllEnemies"),
            "EffectSpawnNiagaraAtTarget": ("Effect_NiagaraData.niagaraAsset", "Effect_NiagaraData.PartName", "Effect_SpawnTarget_bAllTarget"),
            "OtherChangeSubSpaceColor": ("Other_ChangeSubSpaceColor_Color",), "PostSetColorGradingGlobalParameter": ("Post_SetColorGradingGlobalParameter_Id",),
            "UnitMoveToTarget": ("Unit_MoveToTarget_Frame",), "UnitMoveToDefaultLocation": (), "UnitMoveToLocation": (), "BGChange": ("BG_Change_BackgroundLevel",),
            "OtherReaction": (), "CameraShake": (), "CameraSetZoomInOut": (), "UnitStartAfterimage": (), "SoundPlayHitSound": ("Sound_PlayHitSound_playLabel",)}
    events = []; tracks = {}
    for dp, _, fs in os.walk(legacy_dir):
        for f in fs:
            if not f.endswith(".uasset"): continue
            kind = "master" if f.endswith("_Master.uasset") else "cut" if "_Cut" in f else "effect" if "_Effect" in f else "sound" if "_Sound" in f else None
            if not kind: continue
            path = os.path.join(dp, f)
            dump = package_json(path, "seqdump") or {}; tj = package_json(path, "tojson") or {}
            times = key_times(tj) if tj else {}
            tracks[kind] = f[:-7]
            for k, v in dump.items():
                fidx = int(k.split(":")[0]); e = flat(v); t = e.get("EventType")
                if t not in KEEP: continue
                tick, dis = times.get(fidx, (None, False))
                keep = {fld.split(".")[-1] if fld.startswith("Effect_NiagaraData") else fld: val for fld, val in e.items() if fld.startswith(KEEP[t]) and val not in (None, "", 0, -1, False, "None", "soft:None")}
                events.append({"track": kind, "type": t, "t": round(tick / 24000, 2) if tick is not None else None, "disabled": dis, **keep})
            if kind == "sound" and tj:
                ex = tj["Exports"]; imps = tj["Imports"]
                for e in ex:
                    i = e.get("ClassIndex")
                    if not (isinstance(i, int) and i < 0 and imps[-i - 1]["ObjectName"] == "MovieSceneAtomSection"): continue
                    snd = next((p.get("Value") for p in e.get("Data", []) if p.get("Name") == "Sound"), None)
                    rng = next((p for p in e.get("Data", []) if p.get("Name") == "SectionRange"), None)
                    start = None
                    try:
                        lb = next((x for x in rng["Value"][0].values() if isinstance(x, dict) and "LowerBound" in json.dumps(x)[:200]), None)
                        start = first_int(rng["Value"][0].get("LowerBound") or (rng["Value"][0].get("Value") or {}).get("LowerBound") or lb)
                    except Exception: pass
                    name = imps[-snd - 1]["ObjectName"] if isinstance(snd, int) and snd < 0 else None
                    events.append({"track": "sound", "type": "Sound", "t": round(start / 24000, 2) if isinstance(start, (int, float)) else None, "cue": name, "voice": bool(name and name.startswith("VO_"))})
    events.sort(key=lambda e: (e["t"] if e["t"] is not None else 1e9, e["track"]))
    return {"skill": skill_id, "name": sk["name"], "path": sk["seqPath"], "tracks": tracks, "events": events}

# ---------------------------------------------------------------- build / verify / install
LOG_DIR = os.environ.get("FFR_LOG_DIR") or os.path.join(ROOT, "logs")

def heal_sprites(note=print):
    """a unit whose per-unit sprite copy is missing (added before its pack was visible to the engine) gets it from the pack now"""
    import shutil
    for u in load_spec():
        ff = u.get("ffbe") or {}; fid = str(ff.get("id") or ""); rel = ff.get("dir")
        if not fid or not rel: continue
        dst = os.path.join(ROOT, rel)
        if os.path.exists(os.path.join(dst, f"unit_anime_{fid}.png")): continue
        files = ffbe_catalog.sprite_files(fid)
        if not files:
            note(f"  {u.get('key')}: no sprites for look {fid} on this machine (download them by opening the unit, or re-add it)"); continue
        os.makedirs(dst, exist_ok=True)
        for f in files: shutil.copy(f, dst)
        note(f"  {u.get('key')}: sprites for look {fid} copied from the pack ({len(files)} files)")

def run_build(install):
    state.update(running=True, log=[], result=None, started=time.time(), finished=None, stage="Starting", stages=[], install=install, message=None)
    logf = None
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        logf = open(os.path.join(LOG_DIR, f"build-{time.strftime('%Y%m%d-%H%M%S')}.log"), "w", encoding="utf-8")
        logf.write(f"engine {ENGINE_VERSION}, install={install}\n")
    except Exception: logf = None
    def note(line):
        if line.startswith('##stage '):
            state['stage'] = line[8:]; state['stages'].append(line[8:])
            line = '--- ' + line[8:] + ' ---'
        state["log"].append(line)
        if logf:
            try: logf.write(line + "\n"); logf.flush()
            except Exception: pass
    heal_sprites(note)
    cmd = ffrenv.py(os.path.join(ROOT, "tools", "make_vision_mod.py")) + ["--no-install"]   # the server installs (with backups) below
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    try:
        import effect_downloads
        state['stage'] = 'Preparing equipped move effects'
        effect_downloads.ensure_loadout(load_spec(), lambda **kw: state.update(stage=kw.get('stage', state['stage'])))
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
        for line in p.stdout:
            line = line.rstrip("\r\n")
            note(line)
        p.wait()
        if p.returncode == 0:
            state["stage"] = "Verifying the game tables"; state["stages"].append(state["stage"])
            v = subprocess.run(ffrenv.py(os.path.join(ROOT, "tools", "verify_mod.py")), cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
            note(""); note("--- Verifying the game tables ---")
            for line in (v.stdout + v.stderr).splitlines():
                note(line)
            if v.returncode != 0:
                state["result"] = "failed"; state["message"] = "The mod was built, but the table check found unexpected changes. Open the console for details."
            elif install:
                state["stage"] = "Installing into the game"; state["stages"].append(state["stage"]); state["log"].append("--- Installing into the game ---")
                try:
                    r = install_files(note)
                    state["result"] = "ok"; state["message"] = f"Mod built and installed ({r['files']} files{', previous files backed up' if r['backup'] else ''}). Launch the game and visit the Mitra item shop."
                except Exception as ex:
                    state["result"] = "failed"; state["message"] = f"The mod was built but could not be installed: {ex}"
            else:
                state["result"] = "ok"; state["message"] = 'Mod built. Use "Install last build" when the game is closed.'
        else:
            state["result"] = "failed"; state["message"] = f"The build failed while: {state['stage'].lower()}. Open the console for details."
    except Exception as ex:
        note(f"error: {ex}"); state["result"] = "failed"; state["message"] = f"The build could not run: {ex}"
    note(f"result: {state['result']}  {state.get('message') or ''}")
    if logf:
        try: logf.close()
        except Exception: pass
    state["stage"] = "Done"; state["running"] = False; state['finished'] = time.time()

@app.post("/api/build")
async def build(req: Request):
    body = await req.json() if req.headers.get("content-length") not in (None, "0") else {}
    install = bool(body.get("install"))
    if state["running"]: raise HTTPException(409, "a build is running")
    if install and game_running(): raise HTTPException(409, "the game is running: close it before installing")
    import setup as studio_setup
    left = studio_setup.missing()
    if left: raise HTTPException(409, "the game's data is not fully prepared (" + "; ".join(left) + "). Prepare again from the setup page.")
    state["running"] = True
    threading.Thread(target=run_build, args=(install,), daemon=True).start()
    return {"ok": True}

@app.get("/api/build/log")
def build_log(): return {"running": state["running"], "result": state["result"], "log": state["log"][-600:], "started": state["started"],
                         "finished": state.get('finished'),
                         "stage": state.get("stage"), "stages": state.get("stages", []), "message": state.get("message"), "install": state.get("install")}

# ---------------------------------------------------------------- the game folder: install with backups, restore to original
# Everything the studio puts into the game folder is recorded in <engine>/game_state.json. A file that already sat under one of
# our names is copied to <engine>/backups/<timestamp>/ first. "Restore" removes what we placed and puts the originals back.
GAME_STATE = os.path.join(ROOT, "game_state.json")
BACKUPS = os.path.join(ROOT, "backups")
MOD_FILES = [f"zzz_{ffrenv.MOD_NAME}_P.{ext}" for ext in ("utoc", "ucas", "pak")]
MODS_REL = "FFRS/Content/Paks/~mods"

def _game_state():
    if os.path.exists(GAME_STATE):
        try: return json.load(open(GAME_STATE, encoding="utf-8"))
        except Exception: pass
    return {"placed": [], "original": {}, "createdModsDir": False, "installs": []}

def _save_game_state(st): json.dump(st, open(GAME_STATE, "w", encoding="utf-8"), indent=1)

def _game_root(paks): return os.path.dirname(os.path.dirname(os.path.dirname(paks)))

def install_files(log=lambda s: None):
    """copies the built pak set into <game>/FFRS/Content/Paks/~mods, backing up whatever those names held before"""
    import shutil
    if game_running(): raise RuntimeError("the game is running: close it before installing")
    paks = game_paks()
    if not paks: raise RuntimeError("the game folder is not set")
    src = os.path.join(ROOT, "build", "out")
    files = [f for f in MOD_FILES if os.path.exists(os.path.join(src, f))]
    if len(files) != len(MOD_FILES): raise RuntimeError("nothing to install yet: build the mod first")
    import addon_install
    sources = {f: os.path.join(src, f) for f in files}
    addons, addon_work = addon_install.prepare(paks, sources, log)
    if addon_work:
        sources = {f: os.path.join(addon_work, 'game', MODS_REL, f) for f in files}
    sources.update(addons)
    if game_running(): raise RuntimeError('The game was opened during preparation. Close it before installing.')
    st = _game_state(); dst = os.path.join(paks, "~mods")
    if not os.path.isdir(dst): os.makedirs(dst); st["createdModsDir"] = True
    stamp = time.strftime("%Y%m%d_%H%M%S"); bdir = os.path.join(BACKUPS, stamp); backed = []
    log('##stage Backing up the previous installation')
    for f in sources:
        t = os.path.join(dst, f)
        if os.path.exists(t):
            os.makedirs(bdir, exist_ok=True); shutil.copy2(t, os.path.join(bdir, f)); backed.append(f)
            # a name we never placed ourselves: that file is the game's original state for the name
            if f in files and f"{MODS_REL}/{f}" not in st["placed"] and f"{MODS_REL}/{f}" not in st.get("original", {}):
                st.setdefault("original", {})[f"{MODS_REL}/{f}"] = f"{stamp}/{f}"
    try:
        log('##stage Copying the updated mod into the game')
        for f, source in sources.items():
            shutil.copy2(source, os.path.join(dst, f)); log(f"  placed {MODS_REL}/{f}")
            if f in files and f"{MODS_REL}/{f}" not in st["placed"]: st["placed"].append(f"{MODS_REL}/{f}")
    except Exception:
        for f in sources:
            target = os.path.join(dst, f)
            if f in backed: shutil.copy2(os.path.join(bdir, f), target)
            elif os.path.isfile(target): os.remove(target)
        raise
    if backed: log(f"  previous files backed up to backups/{stamp}")
    st["installs"].append({"time": stamp, "files": files, "backup": stamp if backed else None, "game": _game_root(paks),
                           "refreshedAddons": list(addons), "addonVerification": addon_work})
    _save_game_state(st)
    return {"files": len(sources), "backup": stamp if backed else None}

def restore_game(backup=None):
    """backup=None: back to the original game (remove everything we placed, put back what was there before us).
       backup=<stamp>: put that backup's files back (roll back to the previous install)."""
    import shutil
    if game_running(): raise RuntimeError("the game is running: close it before restoring")
    paks = game_paks()
    if not paks: raise RuntimeError("the game folder is not set")
    game = _game_root(paks); st = _game_state(); removed = []; restored = []
    if backup:
        bdir = os.path.join(BACKUPS, backup)
        if not os.path.isdir(bdir): raise RuntimeError(f"no backup {backup}")
        os.makedirs(os.path.join(paks, "~mods"), exist_ok=True)
        for f in os.listdir(bdir):
            shutil.copy2(os.path.join(bdir, f), os.path.join(paks, "~mods", f)); restored.append(f"{MODS_REL}/{f}")
        st["installs"].append({"time": time.strftime("%Y%m%d_%H%M%S"), "rollback": backup, "restored": restored}); _save_game_state(st)
        return {"removed": removed, "restored": restored, "backup": backup}
    for rel in list(st["placed"]):
        t = os.path.join(game, rel)
        if os.path.exists(t): os.remove(t); removed.append(rel)
    # our own names even when this record never saw them (an older studio version, a copy by hand)
    for f in MOD_FILES:
        t = os.path.join(paks, "~mods", f)
        if os.path.exists(t) and f"{MODS_REL}/{f}" not in st.get("original", {}): os.remove(t); removed.append(f"{MODS_REL}/{f}")
    for rel, b in st.get("original", {}).items():
        src = os.path.join(BACKUPS, b)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(os.path.join(game, rel)), exist_ok=True); shutil.copy2(src, os.path.join(game, rel)); restored.append(rel)
    mods = os.path.join(paks, "~mods")
    if st.get("createdModsDir") and os.path.isdir(mods) and not os.listdir(mods): os.rmdir(mods); removed.append(MODS_REL + "/")
    st["placed"] = []; st["original"] = {}; st["createdModsDir"] = False
    st["installs"].append({"time": time.strftime("%Y%m%d_%H%M%S"), "restore": True, "removed": removed, "restored": restored})
    _save_game_state(st)
    return {"removed": removed, "restored": restored, "backup": None}

def game_files():
    """what sits in the game's ~mods folder right now, and which backups exist"""
    paks = game_paks(); present = []
    if paks:
        mods = os.path.join(paks, "~mods")
        for f in sorted(os.listdir(mods)) if os.path.isdir(mods) else []:
            p = os.path.join(mods, f)
            if os.path.isfile(p): present.append({"path": f"{MODS_REL}/{f}", "size": os.path.getsize(p), "ours": f in MOD_FILES})
    backups = []
    for d in sorted(os.listdir(BACKUPS)) if os.path.isdir(BACKUPS) else []:
        bd = os.path.join(BACKUPS, d)
        if os.path.isdir(bd): backups.append({"id": d, "files": sorted(os.listdir(bd)), "size": sum(os.path.getsize(os.path.join(bd, f)) for f in os.listdir(bd))})
    return {"present": present, "backups": backups, "record": _game_state()}

@app.post("/api/install")
def install_only():
    if state['running']: raise HTTPException(409, 'a build or installation is running')
    state.update(running=True, log=[], result=None, started=time.time(), finished=None,
                 stage='Preparing installation', stages=[], install=True, message=None)
    def note(line):
        if line.startswith('##stage '):
            state['stage'] = line[8:]; state['stages'].append(line[8:])
            line = '--- ' + line[8:] + ' ---'
        state['log'].append(line)
    try:
        r = install_files(note)
        state['message'] = 'Mod installed. Launch the game and visit the Mitra item shop.'; state['result'] = 'ok'
    except Exception as ex:
        state['result'] = 'failed'; state['message'] = f'The mod could not be installed: {ex}'
        raise HTTPException(409, str(ex)) from ex
    finally:
        state.update(running=False, finished=time.time(), stage='Done')
    return {"ok": True, **r, "message": state["message"]}

@app.get("/api/game/files")
def api_game_files(): return game_files()

@app.post("/api/game/restore")
async def api_game_restore(req: Request):
    body = await req.json() if req.headers.get("content-length") not in (None, "0") else {}
    try: r = restore_game(body.get("backup"))
    except RuntimeError as ex: raise HTTPException(409, str(ex))
    state["message"] = "Backup put back." if body.get("backup") else "The game folder is back to its original files."; state["result"] = "ok"
    return {"ok": True, **r, "message": state["message"]}

@app.get("/api/status")
def status():
    import setup as studio_setup
    import converted_units
    units = load_spec(); paks = game_paks(); missing = studio_setup.missing()
    return {"gameRunning": game_running(), "spec": SPEC, "units": len(units), "building": state["running"], "lastResult": state["result"],
            "modInstalled": bool(paks) and os.path.exists(os.path.join(paks, "~mods", f"zzz_{ffrenv.MOD_NAME}_P.utoc")),
            "gameRoot": ffrenv.detect_game(), "packaged": ffrenv.FROZEN, "setupNeeded": bool(missing) and not setup_state["running"], "setupMissing": missing,
            "engineVersion": ENGINE_VERSION,
            "ffbeDataDir": ffbe_catalog.PACK,
            "localConvertedCatalog": converted_units.manifest() is not None,
            "unitIndexCache": os.environ.get("FFR_HOST_INDEX", str(unit_downloads.app_root() / "ffbe_index_cache.json")),
            "backups": sum(1 for d in (os.listdir(BACKUPS) if os.path.isdir(BACKUPS) else []) if os.path.isdir(os.path.join(BACKUPS, d))),
            "placed": len(_game_state().get("placed", []))}

@app.post("/api/shutdown")
def shutdown():
    """the native app stops the engine with this; the process exits after the response is sent"""
    def later():
        time.sleep(0.3); os._exit(0)
    threading.Thread(target=later, daemon=True).start()
    return {"ok": True}

# ---------------------------------------------------------------- first-run preparation (tools/devui/setup.py)
setup_state = {"running": False, "log": [], "result": None}
def run_setup(game):
    import setup as studio_setup
    setup_state.update(running=True, log=[], result=None)
    try:
        studio_setup.prepare(game, log=lambda m: setup_state["log"].append(str(m)))
        setup_state["result"] = "ok"
    except Exception as ex:
        setup_state["log"].append(f"error: {ex}"); setup_state["result"] = "failed"
    setup_state["running"] = False

@app.post("/api/setup")
async def setup_start(req: Request):
    body = await req.json() if req.headers.get("content-length") not in (None, "0") else {}
    if setup_state["running"]: raise HTTPException(409, "already preparing")
    game = (body.get("game") or "").strip() or ffrenv.detect_game()
    if not ffrenv.is_game_root(game): raise HTTPException(400, "that folder does not contain FFRS/Content/Paks/FFRS-Windows.utoc")
    threading.Thread(target=run_setup, args=(game,), daemon=True).start()
    return {"ok": True}

@app.get("/api/setup/log")
def setup_log(): return {"running": setup_state["running"], "result": setup_state["result"], "log": setup_state["log"][-200:]}

# Attack Lab is registered before the static catch-all.
import attack_lab
attack_lab.register(app, sys.modules[__name__])

# ---------------------------------------------------------------- static front end
DIST = os.path.join(HERE, "web", "dist")
if os.path.isdir(DIST):
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("DEVUI_PORT", "8765")))
