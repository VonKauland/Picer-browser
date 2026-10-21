"""Concrete impact cases, safe baselines and no duplicate/unrelated commands."""

import json
import shutil
import subprocess
import textwrap

import pytest

from scripts.validate_changes import (
    ROOT,
    SCOPES,
    changed_paths,
    make_plan,
    run_plan,
    validated_base,
)


def test_popup_style_change_has_visual_checks_but_no_packaging_or_raw_tests():
    plan = make_plan(["src/picer/theme.py"])
    assert "tests/test_popup_rendering.py" in plan["tests"]
    assert "tests/test_settings_ui.py" in plan["tests"]
    assert "tests/test_camera_regions.py" not in plan["tests"]
    assert "tests/test_installer.py" not in plan["tests"]
    assert plan["lint"] == ["src/picer/theme.py"]
    assert not plan["full"] and not plan["build"] and not plan["installer"]


def test_changed_unit_test_runs_itself_without_unrelated_gui_tests():
    plan = make_plan(["tests/test_camera_metadata.py"])
    assert "tests/test_camera_metadata.py" in plan["tests"]
    assert "tests/test_about.py" not in plan["tests"]
    assert not plan["build"]


def test_docs_only_needs_no_dependency_install_or_tests():
    plan = make_plan(["README.md", "docs/distribution.md", "AGENTS.md"])
    assert not plan["needs_environment"]
    assert plan["tests"] == plan["lint"] == []
    assert not plan["build"] and not plan["installer"]


def test_core_decoder_reaches_transitive_consumers():
    plan = make_plan(["src/picer/imaging.py"])
    for path in (
        "test_media",
        "test_shared_thumbnails",
        "test_shell_thumbnail",
        "test_image_manager",
    ):
        assert f"tests/{path}.py" in plan["tests"]
    assert not plan["build"]


@pytest.mark.parametrize(
    "folder,expected",
    [
        ("file_browser", "test_browser_commands"),
        ("image_editor", "test_editing"),
        ("info_panel", "test_info_annotations"),
        ("progress_panel", "test_progress_layout"),
    ],
)
def test_dynamic_plugin_paths_have_explicit_consumers(folder, expected):
    plan = make_plan([f"examples/{folder}/manifest.json"])
    assert f"tests/{expected}.py" in plan["tests"]
    assert "tests/test_plugins.py" in plan["tests"]
    assert not plan["full"] and not plan["installer"]


def test_native_change_requests_packaged_abi_validation_but_not_installer():
    plan = make_plan(["native/thumbnail_provider.cpp"])
    assert "tests/test_shell_thumbnail.py" in plan["tests"]
    assert plan["build"] and not plan["installer"] and not plan["full"]


def test_installer_change_requests_all_distribution_steps_but_scoped_pytest():
    plan = make_plan(["installer/Picer.iss"])
    assert plan["build"] and plan["installer"]
    assert "tests/test_installer.py" in plan["tests"]
    assert "tests/test_camera_regions.py" not in plan["tests"]


@pytest.mark.parametrize(
    "path", ["requirements.txt", "requirements-dev.txt", "pyproject.toml", "tests/conftest.py"]
)
def test_shared_test_inputs_expand_to_complete_suite(path):
    plan = make_plan([path])
    assert plan["full"]
    assert len(plan["tests"]) == len(list((ROOT / "tests").glob("test_*.py")))


def test_release_overrides_small_diff_and_builds_verified_installable_assets():
    plan = make_plan(["docs/releases/v0.25.0.md"], release=True, preview=True)
    assert plan["full"] and plan["build"] and plan["installer"] and plan["tests"]
    assert not plan["preview"]


def test_explicit_portable_build_keeps_scoped_tests_and_preview_is_distinct():
    regular = make_plan(["src/picer/theme.py"], artifacts="portable")
    assert regular["build"] and not regular["installer"] and regular["tests"]
    preview = make_plan(["src/picer/theme.py"], preview=True)
    assert preview["preview"] and preview["build"] and not preview["installer"]
    assert not preview["tests"] and not preview["lint"]


@pytest.mark.parametrize(
    "path", ["new-config.toml", "src/picer/new_unmapped.py", "examples/unknown/manifest.json"]
)
def test_unknown_impact_cannot_silently_skip_tests(path):
    plan = make_plan([path])
    assert plan["full"] and plan["tests"]


@pytest.mark.parametrize("path", ["/tmp/private.py", "../outside.py", "src\\picer\\theme.py"])
def test_paths_cannot_escape_repository(path):
    with pytest.raises(ValueError):
        make_plan([path])


def test_scope_names_still_reference_real_tests():
    for scopes in SCOPES.values():
        for name in scopes:
            assert (ROOT / "tests" / (name + ".py")).is_file()


def fixture_repo(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    for name in ("old name.py", "tracked.py"):
        (tmp_path / name).write_text("# fixture\n" * 50, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "user.name=Fixture",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()


def test_diff_keeps_both_rename_paths_and_untracked_and_unstaged_work(tmp_path):
    base = fixture_repo(tmp_path)
    subprocess.run(["git", "mv", "old name.py", "新名称.py"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.py").write_text("# edited\n", encoding="utf-8")
    (tmp_path / "new file.py").write_text("# new\n", encoding="utf-8")
    assert set(changed_paths(base, tmp_path)) == {
        "old name.py",
        "新名称.py",
        "tracked.py",
        "new file.py",
    }


def test_baseline_rejects_preview_current_head_and_unreachable_commits(tmp_path):
    base = fixture_repo(tmp_path)
    history = {
        "head": "b" * 40,
        "base": base,
        "runs": [
            {"sha": "b" * 40, "message": "same head", "validated": True},
            {"sha": base, "message": "[portable-preview]", "validated": True},
            {"sha": "a" * 40, "message": "unreachable", "validated": True},
            {"sha": "--malicious", "message": "invalid ref", "validated": True},
            {"sha": base, "message": "green preview without validation", "validated": False},
        ],
    }
    assert validated_base(history, root=tmp_path) == base  # Event-base fallback.
    history["base"] = ""
    assert validated_base(history, root=tmp_path) == ""
    history["runs"].append({"sha": base, "message": "validated", "validated": True})
    assert validated_base(history, root=tmp_path) == base


def test_manual_artifact_build_can_reuse_current_success_without_repeating_tests(tmp_path):
    base = fixture_repo(tmp_path)
    history = {
        "head": base,
        "base": "",
        "runs": [{"sha": base, "message": "validated", "validated": True}],
    }
    assert validated_base(history, root=tmp_path) == ""
    assert validated_base(history, root=tmp_path, allow_current=True) == base
    plan = make_plan([], artifacts="portable")
    assert plan["build"] and not plan["tests"]


def test_relative_and_literal_dynamic_imports_reach_tests_without_running_code(tmp_path):
    files = {
        "src/picer/__init__.py": "",
        "src/picer/source.py": "VALUE = 1\n",
        "src/picer/consumer.py": "from . import source\n",
        "tests/test_one.py": 'import importlib\nimportlib.import_module("picer.consumer")\n',
        "tests/test_unrelated.py": "VALUE = 1\n",
        "tests/nested/test_extra.py": "import picer.consumer\n",
    }
    for path, content in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    plan = make_plan(["src/picer/source.py"], root=tmp_path)
    expected = ["tests/nested/test_extra.py", "tests/test_one.py"]
    assert plan["tests"] == expected and not plan["full"]
    assert make_plan(["src/picer/__init__.py"], root=tmp_path)["tests"] == expected
    (tmp_path / "src/picer/source.py").unlink()
    assert make_plan(["src/picer/source.py"], root=tmp_path)["tests"] == expected


def test_missing_suite_is_an_error_instead_of_a_successful_empty_run(tmp_path):
    with pytest.raises(ValueError, match="No test suite"):
        make_plan(["new_source.py"], root=tmp_path)


def test_executor_runs_each_tool_once_and_skips_pytest_for_documentation(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: calls.append(command))
    plan = make_plan(["src/picer/theme.py", "src/picer/theme.py"])
    run_plan(plan)
    assert len(calls) == 3
    assert calls[0][2:4] == ["ruff", "check"]
    pytest = calls[-1]
    assert len([p for p in pytest if p.startswith("tests/")]) == len(set(plan["tests"]))
    calls.clear()
    run_plan(make_plan(["README.md"]))
    assert not calls


def test_workflow_preserves_verified_artifact_and_release_gates():
    workflow = (ROOT / ".github/workflows/build-windows.yml").read_text(encoding="utf-8")
    assert "fetch-depth: 0" in workflow and "status: 'success'" in workflow
    assert "--history build/validation-history.json" in workflow
    assert "Run affected checks once" in workflow
    assert "Check native window frame and edge hover" not in workflow
    assert "--compiler-preflight" not in workflow
    assert "needs.build.outputs.release_ready == 'true'" in workflow
    assert "steps.plan.outputs.build == 'true' && steps.plan.outputs.preview != 'true'" in workflow
    assert "if: steps.plan.outputs.installer == 'true'" in workflow
    assert "--draft" in workflow and "--draft=false" in workflow


def test_plan_can_be_serialized_for_ci():
    plan = make_plan(["src/picer/locales/zh_TW.json"])
    assert json.loads(json.dumps(plan)) == plan
    assert "tests/test_i18n_updates.py" in plan["tests"]
    assert not plan["build"]


@pytest.mark.skipif(shutil.which("node") is None, reason="GitHub baseline JavaScript needs Node")
@pytest.mark.parametrize("api_failure", [False, True])
def test_github_history_requires_actual_completed_checks_not_just_green_runs(api_failure):
    workflow = (ROOT / ".github/workflows/build-windows.yml").read_text(encoding="utf-8")
    start = workflow.index("          script: |\n") + len("          script: |\n")
    end = workflow.index("      - name: Set up Python", start)
    script = textwrap.dedent(workflow[start:end])
    setup = r"""
const vm = require('vm');
let written;
const current = 'c'.repeat(40), base = 'b'.repeat(40), valid = 'a'.repeat(40);
const runs = [
  {id: 1, head_sha: current, head_commit: {message: 'same commit'}},
  {id: 2, head_sha: 'd'.repeat(40), head_commit: {message: '[portable-preview]'}},
  {id: 3, head_sha: 'e'.repeat(40), head_commit: {message: 'success without checks'}},
  {id: 33, head_sha: '9'.repeat(40), head_commit: {message: 'different base'},
    event: 'pull_request', pull_requests: [{base: {sha: 'f'.repeat(40)}}]},
  {id: 4, head_sha: valid, head_commit: {message: 'verified'}}
];
const sandbox = {
  process: {env: {PICER_HEAD: current, PICER_EVENT: 'pull_request', PICER_BRANCH: 'feature'}},
  context: {repo: {owner: 'owner', repo: 'repo'}, payload: {pull_request: {base: {sha: base}}}},
  core: {warning: () => {}},
  require: name => {
    if (name === 'child_process') return {execFileSync: (command, args) => {
      if (args.includes('f'.repeat(40))) throw Error('different base');
    }};
    if (name === 'fs') return {
      mkdirSync: () => {}, writeFileSync: (p, s) => {written = JSON.parse(s)}
    };
    throw Error(name);
  },
  github: {rest: {actions: {
    listWorkflowRuns: async () => {
      if (API_FAILURE) throw Error('unavailable');
      return {data: {workflow_runs: runs}};
    },
    listJobsForWorkflowRun: async ({run_id}) => ({data: {jobs: [{
      name: 'Test and build Windows x64',
      steps: [{name: 'Record completed validation',
        conclusion: [4, 33].includes(run_id) ? 'success' : 'skipped'}]
    }]}})
  }}}
};
"""
    code = setup.replace("API_FAILURE", str(api_failure).lower())
    code += (
        "\nvm.runInNewContext('(async () => {' + " + json.dumps(script) + " + '\\n})()', sandbox)"
    )
    code += (
        ".then(() => console.log(JSON.stringify(written)))"
        ".catch(e => {console.error(e); process.exit(1)});"
    )
    result = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    history = json.loads(result.stdout)
    assert history["base"] == "b" * 40
    assert history["runs"] == (
        [] if api_failure else [{"sha": "a" * 40, "message": "verified", "validated": True}]
    )
