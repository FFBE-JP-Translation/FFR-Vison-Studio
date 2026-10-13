r"""ffbe_live.py - decrypt + decode FFBE master tables straight from the JP live client cache (AndApp) or any folder of
Ver<N>_<hash>.dat files, using the key list the user already has (list.json) and the column-name decodes (field_names.json).

python tools/devui/ffbe_live.py [table ...]      -> build/devui/live_jp/<TABLE>.json (list of rows with readable column names)
Default tables: the ones the unit database needs. Encryption: each line = base64(AES-128-CBC(json)), key = 8 ASCII chars + NULs,
IV dZMjkk8gFDzKHlsx, two rounds of trailing-byte padding removal (recipe from T:\Projects\ffbe\FFBE Dump\Decryption\decrypt.py).
"""
import base64, glob, json, os, re, sys
from Crypto.Cipher import AES

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIVE = r"C:\Users\Raegen\AppData\Roaming\AndApp\GameData\5701868182306816\5574872228495360\public"
LIST = r"T:\ffbe_patch\keys\list.json"
FIELDS = r"T:\ffbe_patch\keys\field_names.json"
OUT = os.path.join(ROOT, "build", "devui", "live_jp")
IV = b"dZMjkk8gFDzKHlsx"
DEFAULT_TABLES = ["F_UNIT_MST", "F_UNIT_EXPLAIN_MST", "F_ABILITY_MST", "F_ABILITY_EXPLAIN_MST", "F_MAGIC_MST", "F_LIMITBURST_LV_MST",
                  "F_UNIT_SERIES_LV_ACQUIRE_MST", "F_UNIT_CLASS_UP_MST", "F_UNIT_ROLE_MST", "F_UNIT_GROW_MST", "F_STATIC_UNIT_MST"]

def key_list():
    d = json.load(open(LIST, encoding="utf-8"))
    out = {}
    if isinstance(d, dict):
        for name, v in d.items(): out[name] = v
    else:
        for e in d:
            nm = e.get("name") or e.get("table"); out[nm] = e
    return out

def find_dat(folder, file_hash):
    cands = glob.glob(os.path.join(folder, f"Ver*_{file_hash}.dat")) + glob.glob(os.path.join(folder, f"{file_hash}.dat"))
    def ver(p):
        m = re.search(r"Ver(\d+)_", os.path.basename(p)); return int(m.group(1)) if m else -1
    return max(cands, key=ver) if cands else None

def decrypt_lines(path, key):
    kb = key.encode("utf-8").ljust(16, b"\0")
    rows = []
    for line in open(path, "r", encoding="utf-8", errors="ignore"):
        line = line.strip()
        if not line: continue
        data = AES.new(kb, AES.MODE_CBC, IV).decrypt(base64.b64decode(line))
        data = data[:-data[-1]]; data = data[:-data[-1]]
        try: rows.append(json.loads(data.decode("utf-8")))
        except Exception: rows.append({"_raw": data.decode("utf-8", "replace")})
    return rows

def decode_columns(rows, fields):
    return [{fields.get(k, k): v for k, v in r.items()} for r in rows]

def load_table(name, folder=LIVE, force=False):
    """decrypted + decoded rows of a master table (cached as JSON)"""
    os.makedirs(OUT, exist_ok=True)
    cache = os.path.join(OUT, name + ".json")
    if os.path.exists(cache) and not force: return json.load(open(cache, encoding="utf-8"))
    kl = key_list(); ent = kl.get(name)
    if not ent: raise KeyError(f"{name} not in list.json")
    file_hash = ent.get("file") or ent.get("hash"); key = ent.get("key")
    path = find_dat(folder, file_hash)
    if not path: raise FileNotFoundError(f"{name}: no Ver*_{file_hash}.dat under {folder}")
    fields = json.load(open(FIELDS, encoding="utf-8"))
    rows = decode_columns(decrypt_lines(path, key), fields)
    json.dump({"table": name, "file": os.path.basename(path), "rows": rows}, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return {"table": name, "file": os.path.basename(path), "rows": rows}

if __name__ == "__main__":
    names = sys.argv[1:] or DEFAULT_TABLES
    for n in names:
        try:
            t = load_table(n, force=True); rows = t["rows"]
            keys = list(rows[0].keys())[:14] if rows else []
            print(f"{n}: {len(rows)} rows from {t['file']} | columns: {keys}")
        except Exception as ex:
            print(f"{n}: FAILED {ex}")
