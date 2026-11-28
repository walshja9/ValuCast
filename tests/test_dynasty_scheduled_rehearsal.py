"""Check that the daily workflow keeps rehearsals separate from live effects."""

import re
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/daily-public-data.yml"
MODE = "VALUCAST_DYNASTY_REHEARSAL"
ON = f"env.{MODE} == 'true'"
OFF = f"env.{MODE} != 'true'"
SELECTOR = (
    "((github.event_name == 'schedule' && vars.VALUCAST_DYNASTY_REHEARSAL == 'true')"
    " || (github.event_name == 'workflow_dispatch' && inputs.dynasty_only_rehearsal))"
    " && 'true' || 'false'"
)
BUILD = "python scripts/run_daily_public_build.py --only build"
VALIDATE = "python scripts/run_daily_public_build.py --only validate"
REHEARSE = "python scripts/rehearse_dynasty_release.py"


def _workflow():
    return re.sub(r"(?m)^ *#.*\n", "", WORKFLOW.read_text(encoding="utf-8"))


def _job(text, name):
    body = text.split("\njobs:\n", 1)[1]
    match = re.search(rf"(?m)^  {re.escape(name)}:\n", body)
    assert match is not None, name
    return re.split(r"(?m)^  [a-z][a-z0-9-]*:\n", body[match.end():], maxsplit=1)[0]


def _steps(job):
    return re.split(r"(?m)^      - ", job)[1:]


def _property(block, key, spaces):
    # The workflow uses plain or folded scalars for the guarded fields.
    match = re.search(rf"(?m)^{' ' * spaces}{re.escape(key)}: *([^\n]*)", block)
    if match is None:
        return None
    value = match.group(1).strip()
    if value in {">", ">-", ">+", "|", "|-", "|+"}:
        details = []
        for line in block[match.end():].splitlines()[1:]:
            if not line.strip() or not line.startswith(" " * (spaces + 2)):
                break
            details.append(line.strip())
        value = " ".join(details)
    if value.startswith("${{") and value.endswith("}}"):
        value = value[3:-2].strip()
    return " ".join(value.split())


def _only_step(steps, needle, *, mode=None):
    matches = [step for step in steps if needle in step
               and (mode is None or _property(step, "if", 8) == mode)]
    assert len(matches) == 1, (needle, mode, len(matches))
    return matches[0]


def test_daily_rehearsal_is_explicit_opt_in():
    text = _workflow()
    trigger = re.search(
        r"(?m)^      dynasty_only_rehearsal:\n((?:^        [^\n]*\n)+)", text,
    )
    assert trigger is not None
    assert _property(trigger.group(1), "type", 8) == "boolean"
    assert _property(trigger.group(1), "default", 8) == "false"

    refresh = _job(text, "refresh")
    assert _property(refresh, MODE, 6) == SELECTOR
    assert _property(refresh, "needs", 4) == "preflight"
    assert _property(refresh, "if", 4) == "needs.preflight.outputs.proceed == 'true'"


def test_daily_rehearsal_gate_runs_after_build_and_before_would_publish():
    steps = _steps(_job(_workflow(), "refresh"))
    ordinary_build = _only_step(steps, BUILD, mode=OFF)
    rehearsal_build = _only_step(steps, BUILD, mode=ON)
    rank = _only_step(steps, "python scripts/build_prospect_rank_history.py")
    ordinary_validate = _only_step(steps, VALIDATE, mode=OFF)
    qualify = _only_step(steps, REHEARSE + " qualify", mode=ON)
    would_publish = _only_step(steps, REHEARSE + " would-publish", mode=ON)
    ordinary_publish = _only_step(steps, "git push origin master", mode=OFF)

    assert _property(rank, "if", 8) is None
    assert _property(ordinary_validate, "run", 8) == VALIDATE
    assert _property(qualify, "run", 8) == REHEARSE + " qualify"
    assert _property(would_publish, "run", 8) == REHEARSE + " would-publish"
    for step in (ordinary_build, rehearsal_build, rank, ordinary_validate, qualify, would_publish):
        assert _property(step, "continue-on-error", 8) in {None, "false"}
    assert steps.index(ordinary_build) < steps.index(rank) < steps.index(ordinary_validate) < steps.index(ordinary_publish)
    assert steps.index(rehearsal_build) < steps.index(rank) < steps.index(qualify) < steps.index(would_publish)
    assert "git push" not in qualify + would_publish


def test_daily_rehearsal_keeps_candidate_checkout_and_master_prior():
    steps = _steps(_job(_workflow(), "refresh"))
    ordinary_sync = _only_step(steps, "git checkout -B master origin/master")
    pin = _only_step(steps, 'git merge-base --is-ancestor "$master" HEAD')
    prior = _only_step(steps, "Capture immutable prior canonical public snapshot")

    assert _property(ordinary_sync, "if", 8) == OFF
    assert _property(pin, "if", 8) == ON
    assert 'echo "VALUCAST_REHEARSAL_MASTER=$master" >> "$GITHUB_ENV"' in pin
    assert "git checkout" not in pin
    assert _property(prior, "if", 8) is None
    assert 'git show "${VALUCAST_REHEARSAL_MASTER:-HEAD}:data/public/public_dynasty_snapshot.json"' in prior
    assert 'chmod a-w "$prior"' in prior
    assert steps.index(pin) < steps.index(prior) < steps.index(_only_step(steps, BUILD, mode=ON))


def test_daily_rehearsal_never_provides_write_or_paid_settings():
    refresh = _job(_workflow(), "refresh")
    steps = _steps(refresh)
    assert _property(refresh, "RENDER_DEPLOY_HOOK_URL", 6) == (
        "(github.event_name != 'schedule' || vars.VALUCAST_DYNASTY_REHEARSAL != 'true') && "
        "(github.event_name != 'workflow_dispatch' || !inputs.dynasty_only_rehearsal) && "
        "secrets.RENDER_DEPLOY_HOOK_URL || ''"
    )
    checkout = _only_step(steps, "uses: actions/checkout@")
    setup_python = _only_step(steps, "uses: actions/setup-python@")
    assert _property(checkout, "ssh-key", 10) == f"{OFF} && secrets.REFRESH_DEPLOY_KEY || ''"
    assert _property(checkout, "persist-credentials", 10) == OFF
    assert _property(setup_python, "cache", 10) == f"{OFF} && 'pip' || ''"

    ordinary_build = _only_step(steps, BUILD, mode=OFF)
    rehearsal_build = _only_step(steps, BUILD, mode=ON)
    assert _property(ordinary_build, "VALUCAST_BUYS_REVIEW_APPROVED", 10) == (
        "inputs.approve_valucast_buys && '1' || '0'"
    )
    assert _property(ordinary_build, "ANTHROPIC_API_KEY", 10) == "secrets.ANTHROPIC_API_KEY"
    assert _property(ordinary_build, "VALUCAST_SCOUTING_LLM_MAX_GENERATE", 10) == '"300"'
    assert "secrets." not in rehearsal_build
    assert _property(rehearsal_build, "ANTHROPIC_API_KEY", 10) == '""'
    assert _property(rehearsal_build, "VALUCAST_SCOUTING_LLM_MAX_GENERATE", 10) in {"0", "'0'", '"0"'}
    approval = _property(rehearsal_build, "VALUCAST_BUYS_REVIEW_APPROVED", 10)
    assert approval in {"0", "'0'", '"0"'} or "VALUCAST_BUYS_REVIEW_APPROVED=0" in rehearsal_build


def test_daily_rehearsal_skips_every_existing_publish_side_effect():
    text = _workflow()
    steps = _steps(_job(text, "refresh"))
    for effect in ("git commit -m", "git push origin", "scripts/build_post_drafts.py --send"):
        assert _property(_only_step(steps, effect), "if", 8) == OFF
    deploy = _only_step(steps, ' -X POST "$RENDER_DEPLOY_HOOK_URL"')
    assert set(_property(deploy, "if", 8).split(" && ")) == {OFF, "env.RENDER_DEPLOY_HOOK_URL != ''"}

    saves = [step for step in steps if "uses: actions/cache/save@" in step]
    assert len(saves) == 3
    assert all(_property(step, "if", 8) == f"always() && {OFF}" for step in saves)
    assert not any("uses: actions/cache@" in step for step in steps)

    alert = _job(text, "alert-on-missed-day")
    condition = _property(alert, "if", 4)
    assert (
        "always() && github.event_name == 'schedule' && "
        "vars.VALUCAST_DYNASTY_REHEARSAL != 'true' && "
        "(needs.refresh.result == 'failure' || needs.refresh.result == 'cancelled')" == condition
    )
    assert "gh issue create" in alert and "gh issue comment" in alert


def test_daily_rehearsal_uploads_only_the_two_receipts():
    steps = _steps(_job(_workflow(), "refresh"))
    upload = _only_step(steps, "uses: actions/upload-artifact@")
    assert _property(upload, "if", 8) == f"always() && {ON}"
    assert _property(upload, "path", 10) == (
        "${{ runner.temp }}/dynasty-rehearsal/qualification.json "
        "${{ runner.temp }}/dynasty-rehearsal/receipt.json"
    )
    assert steps.index(upload) > steps.index(_only_step(steps, REHEARSE + " would-publish"))
