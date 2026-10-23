"""Skills packaged as manifest.json + prompt.md load (F52).

SkillRegistry read only SKILL.md, so seven built-ins (web_research,
multi_llm_orchestrator, reasoner, ...) and everything skill_converter writes
never loaded. Trust follows the SKILL.md rule: missing = trusted (hand-written),
unknown = quarantined.
"""

from __future__ import annotations

import json

from weebot.application.skills.skill_registry import SkillRegistry


def _pkg(root, name, **extra):
    d = root / name
    d.mkdir()
    (d / "manifest.json").write_text(
        json.dumps({"name": name, "description": "desc", "emoji": "x",
                    "prompt_file": "prompt.md", **extra}),
        encoding="utf-8",
    )
    (d / "prompt.md").write_text("Do the thing.", encoding="utf-8")


def _load(root):
    reg = SkillRegistry(search_paths=[root])
    reg.load_all()
    return reg.list_all()


def test_a_manifest_package_loads_with_its_prompt(tmp_path):
    _pkg(tmp_path, "web_research")
    skill = _load(tmp_path)["web_research"]
    assert skill.description == "desc" and skill.content == "Do the thing."
    assert skill.metadata.trust == "trusted" and skill.metadata.emoji == "x"


def test_an_unknown_manifest_trust_is_quarantined(tmp_path):
    _pkg(tmp_path, "odd", trust="trustd")
    assert _load(tmp_path)["odd"].metadata.trust == "quarantined"


def test_every_builtin_skill_folder_loads():
    import pathlib

    import weebot

    builtin = pathlib.Path(weebot.__file__).parent / "skills" / "builtin"
    loaded = _load(builtin)
    folders = [d.name for d in builtin.iterdir() if d.is_dir() and not d.name.startswith("_")]
    sources = {pathlib.Path(s.source_path).parent.name for s in loaded.values()}
    assert sorted(set(folders) - sources) == []


def test_a_converted_third_party_skill_loads_quarantined(tmp_path):
    # Now that manifests load, converter output must not read as hand-written.
    from weebot.application.skills.skill_converter import SkillConverter

    src = tmp_path / "src" / "thing"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: thing\ndescription: d\n---\n\nbody\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    SkillConverter(skills_dir=out).convert(src)
    assert _load(out)["thing"].metadata.trust == "quarantined"
