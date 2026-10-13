"""Convert structured FFBE abilities into FFR mechanics and audit every record.

    python -X utf8 -B tools/ability_import.py convert
    python -X utf8 -B tools/ability_import.py one 20200 --sources jp --max-level
    python -X utf8 -B tools/ability_import.py export JP_2024/magic/20200
    python -X utf8 -B tools/ability_import.py verify

See docs/25-ability-converter.md for inputs, formats and integration limits.
"""
from ability_converter.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
