"""Check the editable mod source without extracting, building, or installing a mod.

Usage from the Studio repository (omit mod-tools/ from this directory):
    python mod-tools/check_source.py
    python mod-tools/check_source.py --tests

The default check uses only the Python standard library and parses source with
ast, so it never creates bytecode or imports the game-facing entrypoints. The
optional tests are an explicit allowlist of temporary/in-memory fixtures.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import importlib.util
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
import warnings

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent

# Keep these paths explicit: an incomplete source export should fail even when
# the surviving modules no longer import a missing feature's implementation.
REQUIRED = (
    "tools/devui/launcher.py", "tools/devui/server.py", "tools/ffrenv.py",
    "tools/vision_cards.py", "tools/make_vision_card_mod.py",
    "tools/install_vision_cards.py", "tools/devui/vision_card_routes.py",
    "tools/make_vision_mod.py", "tools/devui/custom_units.py",
    "tools/devui/vision_import.py", "tools/devui/studio_grants.py",
    "tools/ability_converter/compiler.py", "tools/ffbe2ss6/build_sprites.py",
    "tools/private/make_party_mod.py", "tools/private/ffr_party_save.py",
    "tools/private/make_npc_battles.py", "tools/private/npc_assets.py",
    "tools/private/battle_music.py", "tools/private/battle_hca.py",
    "tools/private/verify_vision_install.py", "tools/devui/addon_install.py",
    "src/ffr-dt/ffr-dt.csproj", "src/ffr-dt/Program.cs",
    "src/ffr-export/ffr-export.csproj", "src/ffr-export/Program.cs",
    "src/ffr-vision-cards/CMakeLists.txt",
    "src/ffr-vision-cards/mod.cpp", "src/ffr-vision-cards/build.py",
    "src/ffr-vision-cards/main.lua", "src/ffr-vision-cards/state.lua",
    "src/ffr-vision-cards/ui.lua", "src/ffr-vision-cards/probe.lua",
    "src/ffr-availability-native/CMakeLists.txt",
    "src/ffr-availability-native/mod.cpp", "src/ffr-availability-native/build.py",
    "src/ffr-availability-native/bootstrap.py",
    "src/ffr-availability-native/bridge_core.cpp", "src/ffr-availability-native/bridge_core.hpp",
    "src/ffr-availability-native/query_bridge.cpp", "src/ffr-availability-native/query_bridge.hpp",
    "src/ffr-availability-native/tests.cpp", "src/ffr-availability-native/query_tests.cpp",
    "tools/ability_converter/runtime/availability.lua",
    "tools/ability_converter/runtime/native_main.lua",
    "tools/ability_converter/runtime/native_host.lua",
    "tools/devui/web/package.json", "tools/devui/web/package-lock.json",
    "tools/devui/web/src/main.tsx", "tools/devui/web/src/App.tsx",
    "tools/devui/web/src/CustomUnit.tsx", "tools/devui/web/src/Editor.tsx",
    "docs/19-custom-units-battles.md", "docs/20-studio-unit-bundles.md",
    "docs/48-vision-cards.md",
    "data/ability_converter/reviewed-rules.json",
    "requirements.txt", "requirements-dev.txt",
)

GENERATED_DIRECTORIES = {
    ".venv", "venv", "node_modules", "dist", "build", "bin", "obj",
    "__pycache__", ".vite", ".git", "extracted", "logs", "backups",
    "backup", "abilities", "units", "checkpoints",
}
EXTERNAL_TOOL_DIRECTORIES = {
    "downloads", "fmodel", "ue4ss", "uassetapi", "retoc", "repak",
    "vgmstream", "oodle",
}

IMPORT_DISTRIBUTIONS = {
    "Crypto": "pycryptodome", "PIL": "Pillow", "cv2": "opencv-python",
    "fastapi": "fastapi", "uvicorn": "uvicorn", "anyio": "anyio",
    "pydantic": "pydantic", "starlette": "starlette", "numpy": "numpy",
    "pefile": "pefile", "capstone": "capstone", "lupa": "lupa",
}

# Whole suites below manufacture their own files. Selecting classes rather
# than discovery deliberately excludes game/data-dependent integration cases.
FIXTURE_TESTS = (
    "test_ability_skill_ids.SkillIdTests",
    "test_custom_units.CustomUnits",
    "test_addon_install.AddonInstallTests",
    "test_addon_install.InstalledLimitBurstTests",
    "test_ffbe_frames.FrameTransformsTests",
    "test_cooked_command_cache.CommandCacheTests",
    "test_cooked_effect_cache.CookedCacheTests",
    "test_converted_units.LocalConvertedTests",
    "test_ffbe_effect_bundle.EffectsBundle",
    "test_ffbe_effect_bundle.CompressedTextures",
    "test_shared_effect_delivery.SharedEffects",
    "test_vision_kits.VisionKitTests.test_missing_optional_motion_uses_the_same_idle_as_sprite_builder",
    "test_native_editor.NativeEditorTests.test_strongest_compatible_falls_back_without_merging_unrelated_names",
    "test_vision_cards.VisionCardTests.test_featureless_artwork_is_not_arbitrarily_cropped",
    "test_vision_cards.VisionCardTests.test_blank_gl_name_keeps_jp_title_then_translates",
    "test_vision_cards.VisionCardTests.test_native_item_ids_survive_later_imports",
    "test_vision_cards.VisionCardTests.test_max_stats_ignore_growth_modifiers_and_abilities",
)


def inside(path: Path) -> bool:
    return path.resolve().is_relative_to(ROOT)


def label(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def requirements(path: Path, visited: set[Path] | None = None) -> set[str]:
    """Read declarations and nested -r files without running pip."""
    visited = set() if visited is None else visited
    path = path.resolve()
    if not inside(path):
        raise ValueError(f"Requirement include escapes mod-tools: {path}")
    if path in visited:
        return set()
    visited.add(path)
    packages: set[str] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            packages.update(requirements(path.parent / line[3:].strip(), visited))
        else:
            match = re.match(r"([A-Za-z0-9_.-]+)", line)
            if not match:
                raise ValueError(f"Unsupported requirement in {label(path)}: {line}")
            packages.add(re.sub(r"[-_.]+", "-", match[1]).lower())
    return packages


def source_inventory() -> tuple[list[Path], list[str]]:
    """Prune dependencies/output before walking, including source symlinks."""
    files: list[Path] = []
    problems: list[str] = []
    for current, directories, names in os.walk(ROOT, followlinks=False):
        parent = Path(current)
        for name in directories[:]:
            path = parent / name
            relative = path.relative_to(ROOT)
            ignored = name.casefold() in GENERATED_DIRECTORIES
            ignored |= parent == ROOT and name.casefold() == "data"
            ignored |= relative.parts[0] == "tools" and len(relative.parts) == 2 and name.casefold() in EXTERNAL_TOOL_DIRECTORIES
            if ignored:
                directories.remove(name)
                continue
            if not inside(path):
                problems.append(f"Source directory escapes mod-tools: {label(path)} -> {path.resolve()}")
                directories.remove(name)
            elif path.is_symlink() or path.is_junction():
                # Source should be real editable files, even if a link resolves
                # inside the checkout. Do not silently skip its import closure.
                problems.append(f"Linked source directory: {label(path)}")
                directories.remove(name)
        for name in names:
            path = parent / name
            if not inside(path):
                problems.append(f"Source file escapes mod-tools: {label(path)} -> {path.resolve()}")
                continue
            files.append(path)
    # Generated/downloaded data is excluded, except the authored conversion
    # rules that are a required source dependency.
    rules = ROOT / "data/ability_converter/reviewed-rules.json"
    if rules.is_file():
        if inside(rules):
            files.append(rules)
        else:
            problems.append(f"Source rules escape mod-tools: {label(rules)} -> {rules.resolve()}")
    return files, problems


def check_sources() -> tuple[list[str], set[str]]:
    files, problems = source_inventory()
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            problems.append(f"Missing feature source/dependency: {relative}")
    for path in files:
        if path.suffix.lower() in {".pyc", ".pyo", ".pyd", ".exe", ".dll"}:
            problems.append(f"Compiled artifact in source tree: {label(path)}")
    sources: dict[Path, ast.Module] = {}
    for path in sorted(files):
        if path.suffix.lower() != ".py":
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                sources[path] = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as error:
            problems.append(f"Cannot parse {label(path)}: {error}")
    # Historical entrypoints add sibling tool directories to sys.path. Support
    # that layout while still requiring every local import's source in this tree.
    search_roots = {ROOT, *(path.parent for path in sources)}
    module_paths = {path.with_suffix("") for path in sources}
    for path in sources:
        module_paths.update(parent for parent in path.parents if parent.is_relative_to(ROOT))
    def is_module(path: Path) -> bool:
        # Only authored inventory can satisfy an import. A .venv, compiled
        # output, or external tools folder must not conceal missing source.
        return path in module_paths
    local_names = {path.stem for path in sources}
    local_names.update(path.parent.name for path in sources)
    external: dict[str, set[str]] = defaultdict(set)
    for path, tree in sources.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = path.parent
                    for _ in range(node.level - 1):
                        base = base.parent
                    target = base.joinpath(*(node.module or "").split(".")) if node.module else base
                    if not inside(target) or not is_module(target):
                        problems.append(f"Missing relative import in {label(path)}:{node.lineno}: {'.' * node.level}{node.module or ''}")
                    if node.module is None:
                        # from . import foo loads either a sibling module or an
                        # exported name from __init__.py. This tree uses modules.
                        package = sources.get(base / "__init__.py")
                        exports = set()
                        if package:
                            exports = {n.name for n in package.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))}
                            exports.update(n.id for n in ast.walk(package) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
                        for item in node.names:
                            if item.name != "*" and not is_module(base / item.name) and item.name not in exports:
                                problems.append(f"Missing relative module in {label(path)}:{node.lineno}: {item.name}")
                    continue
                names = [node.module] if node.module else []
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in sys.stdlib_module_names:
                    continue
                if any(is_module(root.joinpath(*name.split("."))) for root in search_roots):
                    continue
                external[top].add(f"{label(path)}:{node.lineno}")
    try:
        declared = requirements(ROOT / "requirements-dev.txt")
    except (OSError, ValueError) as error:
        problems.append(str(error))
        declared = set()
    for module, locations in sorted(external.items()):
        package = IMPORT_DISTRIBUTIONS.get(module)
        if package is None:
            problems.append(f"Missing local source or unrecognized dependency {module}: {', '.join(sorted(locations))}")
        elif re.sub(r"[-_.]+", "-", package).lower() not in declared:
            problems.append(f"Undeclared dependency {package} ({module}): {', '.join(sorted(locations))}")
    if "python-multipart" not in declared:
        problems.append("Missing python-multipart dependency for FastAPI uploads")
    print(f"Parsed {len(sources)} Python files; checked feature sources, contained paths, local imports and dependency declarations.")
    return problems, local_names


def run_tests(local_names: set[str]) -> bool:
    # No automatic unittest discovery: most retained tests require legally
    # supplied game assets, generated catalogs, a .NET tool, or a live build.
    paths = [ROOT, ROOT / "tools", ROOT / "tools/devui", ROOT / "tools/tests",
             ROOT / "tools/ffbe2ss6", ROOT / "tools/private", ROOT / "tools/release"]
    sys.path[:0] = [str(path) for path in paths]
    missing = [name for name in ("PIL", "numpy", "cv2", "Crypto") if importlib.util.find_spec(name) is None]
    if missing:
        print(f"Fixture test dependencies are missing: {', '.join(missing)}. Install requirements-dev.txt first.", file=sys.stderr)
        return False
    prior_directory = Path.cwd()
    prior_temp = tempfile.tempdir
    # Keep fixtures in the checkout's ignored build directory. Some managed
    # Windows sandboxes can create a system-temp directory but deny file writes
    # and cleanup in it. This also makes fixture write boundaries predictable.
    temporary_parent = ROOT / "build"
    temporary_parent.mkdir(exist_ok=True)
    try:
        os.chdir(ROOT)
        with tempfile.TemporaryDirectory(prefix="source-check-", dir=temporary_parent) as temporary:
            tempfile.tempdir = temporary
            suite = unittest.defaultTestLoader.loadTestsFromNames(FIXTURE_TESTS)
            result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        tempfile.tempdir = prior_temp
        os.chdir(prior_directory)
    escaped = []
    for name, module in tuple(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if origin and name.split(".")[0] in local_names and not inside(Path(origin)):
            escaped.append(f"{name}: {origin}")
    if escaped:
        print("Tests loaded local source outside mod-tools: " + "; ".join(escaped), file=sys.stderr)
    print("Asset-dependent card/shop, reviewed catalog, private-battle readback, .NET cooking and live-game tests are excluded.")
    return result.wasSuccessful() and not escaped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tests", action="store_true", help="Run only the reviewed fixture-only test allowlist")
    arguments = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Python 3.12 or newer is required for this source tree")
    problems, local_names = check_sources()
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    if arguments.tests and not run_tests(local_names):
        return 1
    print("Source checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
