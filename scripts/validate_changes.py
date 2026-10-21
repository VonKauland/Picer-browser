"""Select related tests and verification from a Git diff; no third-party imports."""

import argparse
import ast
import json
import os
import re
import subprocess
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
UI_TESTS = {
    "test_about",
    "test_appearance_and_ring",
    "test_binding_layout",
    "test_color_picker",
    "test_messages",
    "test_notifications",
    "test_popup_rendering",
    "test_settings_ui",
    "test_example_panels",
    "test_panel_tabs",
    "test_window",
    "test_image_manager",
    "test_info_annotations",
    "test_editing",
    "test_progress_layout",
    "test_navigation_exif",
}
# Composition roots import almost everything. For UI-only/shared integration paths,
# use explicit feature coverage instead of treating every import as a runtime call.
SCOPES = {
    "src/picer/theme.py": UI_TESTS,
    "src/picer/host_style.py": UI_TESTS,
    "src/picer/ui.py": UI_TESTS | {"test_progress_layout", "test_editing"},
    "src/picer/plugins/skins.py": UI_TESTS | {"test_plugins", "test_settings_transfer"},
    "src/picer/windows_integration.py": {
        "test_formats_and_shell",
        "test_installer",
        "test_shell_thumbnail",
    },
    "src/picer/shell_thumbnail.py": {"test_shell_thumbnail", "test_installer"},
    "src/picer/smoke.py": {"test_app", "test_paths_and_distribution"},
    "src/picer/smoke_samples.py": {"test_app", "test_camera_metadata", "test_media"},
    "scripts/entrypoint.py": {"test_app", "test_shell_thumbnail"},
    "scripts/build_windows.py": {"test_paths_and_distribution", "test_distribution_size"},
    "scripts/distribution_size.py": {"test_distribution_size", "test_paths_and_distribution"},
    "scripts/prepare_assets.py": {"test_paths_and_distribution", "test_window"},
    "scripts/build_installer.py": {"test_installer", "test_shell_thumbnail"},
    "scripts/verify_installer.py": {"test_installer"},
    "scripts/release_assets.py": {"test_installer"},
    "scripts/build_thumbnail_provider.py": {"test_shell_thumbnail", "test_installer"},
    "scripts/verify_thumbnail_provider.py": {"test_shell_thumbnail"},
    "scripts/verify_distribution.py": {"test_paths_and_distribution", "test_shell_thumbnail"},
    "scripts/validate_changes.py": {"test_change_validation"},
}
EXAMPLES = {
    "file_browser": {
        "test_example_panels",
        "test_browser_thumbnail_cache",
        "test_browser_commands",
        "test_image_drops",
        "test_psd_and_export",
    },
    "info_panel": {
        "test_example_panels",
        "test_info_annotations",
        "test_navigation_exif",
        "test_camera_regions",
        "test_ai_video",
    },
    "progress_panel": {"test_example_panels", "test_progress_layout", "test_appearance_and_ring"},
    "image_manager": {"test_image_manager", "test_info_annotations", "test_psd_and_export"},
    "image_editor": {"test_editing"},
    "double_page": {"test_inputs_spread", "test_browser_commands"},
    "touch_support": {"test_inputs_spread"},
    "negative_plugin": {"test_plugins", "test_app"},
    "macos_skin": UI_TESTS,
}
GLOBAL_INPUTS = {"requirements.txt", "requirements-dev.txt", "pyproject.toml", "tests/conftest.py"}
PORTABLE_INPUTS = {
    "scripts/build_windows.py",
    "scripts/distribution_size.py",
    "scripts/entrypoint.py",
    "scripts/prepare_assets.py",
    "scripts/verify_distribution.py",
    "scripts/build_thumbnail_provider.py",
    "scripts/verify_thumbnail_provider.py",
    "src/picer/shell_thumbnail.py",
    "src/picer/smoke.py",
    "src/picer/smoke_samples.py",
}
INSTALLER_INPUTS = {
    "scripts/build_installer.py",
    "scripts/verify_installer.py",
    "scripts/release_assets.py",
    "src/picer/windows_integration.py",
}


def git(*args, root=ROOT):
    return subprocess.check_output(["git", *args], cwd=root, encoding="utf-8")


def changed_paths(base, root=ROOT):
    """Include both sides of renames, staged/unstaged changes and untracked files."""
    git("rev-parse", "--verify", "--end-of-options", base + "^{commit}", root=root)
    fields = git("diff", "--name-status", "-z", "--find-renames", base, root=root).split("\0")
    paths = set()
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        count = 2 if status[0] in "RC" else 1
        paths.update(fields[index + 1 : index + count + 1])
        index += count + 1
    paths.update(git("ls-files", "--others", "--exclude-standard", "-z", root=root).split("\0"))
    return sorted(paths - {""})


def validated_base(history, *, root=ROOT, allow_current=False):
    """A previous success is usable only if it actually precedes this checkout."""

    def ancestor(sha):
        return (
            isinstance(sha, str)
            and bool(re.fullmatch(r"[0-9a-f]{40}", sha))
            and (
                subprocess.run(
                    ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
                    cwd=root,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
                == 0
            )
        )

    runs = history.get("runs", [])
    for run in runs if isinstance(runs, list) else []:
        if not isinstance(run, dict):
            continue
        if run.get("validated") is not True:
            continue
        sha = run.get("sha")
        message = run.get("message", "")
        if (
            isinstance(message, str)
            and "[portable-preview]" not in message
            and ((allow_current or sha != history.get("head")) and ancestor(sha))
        ):
            return sha
    fallback = history.get("base")
    return fallback if ancestor(fallback) else ""


def module_name(path):
    path = PurePosixPath(path)
    if path.suffix != ".py":
        return None
    parts = list(path.with_suffix("").parts)
    if parts[0] == "src":
        parts.pop(0)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def dependency_graph(root):
    """Conservative reverse Python import graph, including relative/lazy imports."""
    files = [
        p
        for directory in ("src/picer", "examples", "scripts", "tests")
        for p in (root / directory).rglob("*.py")
    ]
    names = {module_name(p.relative_to(root).as_posix()) for p in files}
    reverse = defaultdict(set)
    for path in files:
        name = module_name(path.relative_to(root).as_posix())
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        dependencies = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                dependencies.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                prefix = node.module or ""
                if node.level:
                    parent = package.split(".")
                    prefix = ".".join(
                        parent[: len(parent) - node.level + 1] + ([prefix] if prefix else [])
                    )
                dependencies.add(prefix)
                dependencies.update(prefix + "." + alias.name for alias in node.names)
            elif isinstance(node, ast.Call) and node.args:
                method = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if method in {"import_module", "__import__"} and isinstance(
                    node.args[0], ast.Constant
                ):
                    value = node.args[0].value
                    if isinstance(value, str):
                        dependencies.add(value)
        for dependency in dependencies:
            # Keep unresolved names too: deletions must still reach their importers.
            if dependency in names or dependency.startswith(
                ("picer.", "examples.", "scripts.", "tests.")
            ):
                reverse[dependency].add(name)
                pieces = dependency.split(".")
                for end in range(1, len(pieces)):
                    parent = ".".join(pieces[:end])
                    if parent in names:
                        reverse[parent].add(name)
    return reverse


def make_plan(paths, *, root=ROOT, full=False, release=False, artifacts="none", preview=False):
    if artifacts not in {"none", "portable", "all"}:
        raise ValueError("Invalid artifact scope")
    paths = sorted(set(paths))
    for path in paths:
        if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or "\\" in path:
            raise ValueError("Changed paths must be repository-relative")
    all_tests = {
        p.relative_to(root).as_posix()
        for p in (root / "tests").rglob("*.py")
        if p.name.startswith("test_") or p.name.endswith("_test.py")
    }
    if not all_tests:
        raise ValueError("No test suite found")
    if release:
        preview = False
    selected, reasons, seeds = set(), [], set()
    full = full or release or bool(set(paths) & GLOBAL_INPUTS)
    build = (
        release or artifacts != "none" or bool(set(paths) & (PORTABLE_INPUTS | INSTALLER_INPUTS))
    )
    installer = release or artifacts == "all" or bool(set(paths) & INSTALLER_INPUTS)
    for path in paths:
        scope = SCOPES.get(path)
        if path.startswith(".github/workflows/"):
            scope = {"test_change_validation"}
        elif path.startswith("src/picer/locales/"):
            scope = {"test_i18n_updates", "test_settings_ui", "test_popup_rendering"}
        elif path.startswith("src/picer/assets/"):
            scope = {
                "test_paths_and_distribution",
                "test_window",
                "test_about",
                "test_example_panels",
            }
        elif path.startswith("native/"):
            scope = {"test_shell_thumbnail", "test_installer"}
            build = True
        elif path.startswith("installer/"):
            scope = {"test_installer", "test_shell_thumbnail"}
            build = installer = True
        elif path.startswith("examples/"):
            parts = PurePosixPath(path).parts
            scope = EXAMPLES.get(parts[1])
            if scope is not None:
                scope = scope | {"test_plugins", "test_components", "test_i18n_updates"}
        if scope is not None:
            matches = {f"tests/{name}.py" for name in scope} & all_tests
            if not matches:
                full = True
                reasons.append(f"Missing test mapping: {path}")
            selected.update(matches)
            reasons.append(f"Feature scope: {path}")
        elif path.endswith(".py"):
            if path in all_tests:
                selected.add(path)
            seeds.add(module_name(path))
        elif path in GLOBAL_INPUTS:
            reasons.append(f"Shared dependencies/configuration: {path}")
            if path != "tests/conftest.py":
                build = installer = True
        elif path.startswith("docs/") or path.endswith(".md") or path in {".gitignore", "LICENSE"}:
            continue
        else:
            full = True
            reasons.append(f"Unknown impact: {path}")
    if seeds and not full:
        try:
            reverse = dependency_graph(root)
            for seed in seeds:
                reached, pending = set(), deque([seed])
                while pending:
                    module = pending.popleft()
                    if module in reached:
                        continue
                    reached.add(module)
                    pending.extend(reverse[module])
                related = {p for p in all_tests if module_name(p) in reached}
                if not related and not seed.startswith("tests."):
                    full = True
                    reasons.append(f"Unmapped Python dependency: {seed}")
                selected.update(related)
            reasons.append("Direct and transitive Python import dependencies")
        except (SyntaxError, OSError, UnicodeError):
            full = True
            reasons.append("Cannot determine Python dependency impact")
    if full:
        selected = all_tests
        reasons.append("Full suite: shared inputs, unknown impact or explicit request")
    lint = sorted(p for p in paths if p.endswith(".py") and (root / p).is_file())
    if full:
        lint = sorted(
            p.relative_to(root).as_posix()
            for directory in ("src", "examples", "scripts", "tests")
            for p in (root / directory).rglob("*.py")
        )
    if preview:
        build, installer, selected, lint = True, False, set(), []
        reasons.append("Explicit portable preview; not a verified artifact")
    if installer:
        build = True
    return {
        "schema": 1,
        "changed": paths,
        "full": full,
        "release": release,
        "preview": preview,
        "tests": sorted(selected),
        "lint": lint,
        "build": build,
        "installer": installer,
        "needs_environment": bool(selected or lint or build),
        "reasons": sorted(set(reasons)),
    }


def run_plan(plan, *, root=ROOT, junit=None):
    if plan["lint"]:
        for command in (("ruff", "check"), ("ruff", "format", "--check")):
            subprocess.run(
                [os.sys.executable, "-m", *command, "--", *plan["lint"]], cwd=root, check=True
            )
    if plan["tests"]:
        command = [
            os.sys.executable,
            "-m",
            "pytest",
            "--maxfail=1",
            "-o",
            "faulthandler_timeout=120",
        ]
        if junit:
            command += ["--junitxml=" + str(junit)]
        targets = ["tests"] if plan["full"] else plan["tests"]
        subprocess.run([*command, *targets], cwd=root, check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--history", type=Path)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--artifacts", choices=("none", "portable", "all"), default="none")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--junit", type=Path)
    parser.add_argument("--output", type=Path, default=Path("build/validation-plan.json"))
    parser.add_argument("--execute-plan", type=Path)
    args = parser.parse_args(argv)
    if args.execute_plan:
        plan = json.loads(args.execute_plan.read_text(encoding="utf-8"))
        run_plan(plan, junit=args.junit)
        return
    if args.history:
        try:
            history = json.loads(args.history.read_text(encoding="utf-8"))
            args.base = (
                validated_base(
                    history, allow_current=os.environ.get("PICER_EVENT") == "workflow_dispatch"
                )
                if isinstance(history, dict)
                else ""
            )
        except (OSError, ValueError, TypeError):
            args.base = ""
    event = os.environ.get("PICER_EVENT", "")
    head = os.environ.get("PICER_HEAD", "HEAD")
    message = git("show", "-s", "--format=%B", head)
    release = (
        event == "push" and os.environ.get("PICER_BRANCH") == "main" and "[release]" in message
    )
    preview = event == "pull_request" and "[portable-preview]" in message
    full = args.full or os.environ.get("PICER_FULL") == "true"
    artifacts = os.environ.get("PICER_ARTIFACTS") or args.artifacts
    if "[installer]" in message:
        artifacts = "all"
    elif "[build]" in message and artifacts == "none":
        artifacts = "portable"
    try:
        paths = changed_paths(args.base)
    except (subprocess.CalledProcessError, OSError):
        paths = [p for p in git("ls-files", "-z").split("\0") if p]
        full = True
    plan = make_plan(paths, full=full, release=release, artifacts=artifacts, preview=preview)
    plan["base"] = args.base
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            for key in ("build", "installer", "needs_environment", "preview", "release", "full"):
                handle.write(f"{key}={str(plan[key]).lower()}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(f"### Validation plan\n\nBase: `{args.base}`\n\n")
            handle.write(
                f"Tests: {len(plan['tests'])}; full: {plan['full']}; "
                f"build: {plan['build']}; installer: {plan['installer']}\n\n"
            )
            handle.write("\n".join("- `" + path + "`" for path in plan["tests"]) + "\n")
    if args.run:
        run_plan(plan, junit=args.junit)


if __name__ == "__main__":
    main()
