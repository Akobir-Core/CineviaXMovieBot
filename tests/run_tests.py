from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_static import test_python_syntax, test_locales_have_same_keys, test_schema_builds, test_local_callback_coverage, test_env_example_safe, test_multiepisode_architecture, test_series_anime_sql_behaviour, test_security_schema_and_required_channels, test_core_security_static


def main() -> None:
    for test in (test_python_syntax, test_locales_have_same_keys, test_schema_builds, test_local_callback_coverage, test_env_example_safe, test_multiepisode_architecture, test_series_anime_sql_behaviour, test_security_schema_and_required_channels, test_core_security_static):
        test()
    print("STATIC TESTS: PASS")


if __name__ == "__main__":
    main()
