"""Dotfiles sync engine for SigmaOS-dots-configuration (inspired by omadots).

Principles: manifest-driven (single source of truth), plan-before-act
(link/sync are dry-run by default, --execute mutates), defensive parsing
(no absolute targets, no path escapes), backup before replace, hashes for
diffs, profiles isolate user personas.
"""
import argparse, hashlib, os, sys

ENGINE = {
    "name": "sigma-dots",
    "summary": "Link, sync, back up and diff dotfile profiles",
    "language": "python",
    "verbs": ["link", "sync-plan", "backup", "diff", "profile"],
    "principles": ["Single Source of Truth", "Plan Before Act",
                   "Defensive Programming", "Fail-Fast", "Least Astonishment",
                   "KISS", "DRY"],
}

cli_doc = """\
$ sigma-dots profile --profiles ./profiles
workstation  link:3 copy:1
server       link:1 copy:0
$ sigma-dots link --profiles ./profiles --profile work --home ~/. --execute
link .bashrc -> ~/.bashrc
$ sigma-dots sync-plan --profiles ./profiles --profile work --home ~/
copy .config/git/ignore  (content differs)
$ sigma-dots diff --profiles ./profiles --profile work --home ~/
match .bashrc
$ sigma-dots backup --profiles ./profiles --profile work --home ~/ --to ~/.dots-backup
"""

_MODES = ("link", "copy")


class DotsError(ValueError):
    pass


def parse_manifest(text):
    """Parse `mode target [source]` lines into validated entries."""
    entries, seen = [], set()
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) not in (2, 3):
            raise DotsError(f"line {lineno}: expected 'mode target [source]'")
        mode, target = parts[0], parts[1]
        source = parts[2] if len(parts) == 3 else target
        if mode not in _MODES:
            raise DotsError(f"line {lineno}: bad mode {mode!r} "
                            f"(want one of {_MODES})")
        if os.path.isabs(target) or target.split("/")[0] == ".." \
                or target in (".", "..") or "\x00" in target:
            raise DotsError(f"line {lineno}: unsafe target {target!r}")
        if os.path.isabs(source) or source.split("/")[0] == ".." \
                or "\x00" in source:
            raise DotsError(f"line {lineno}: unsafe source {source!r}")
        if target in seen:
            raise DotsError(f"line {lineno}: duplicate target {target!r}")
        seen.add(target)
        entries.append({"mode": mode, "target": target, "source": source})
    if not entries:
        raise DotsError("manifest is empty")
    return entries


def list_profiles(profiles_dir):
    """Profile names = subdirectories that contain a 'manifest' file."""
    if not os.path.isdir(profiles_dir):
        raise DotsError(f"no such profiles dir: {profiles_dir!r}")
    out = []
    for name in sorted(os.listdir(profiles_dir)):
        manifest = os.path.join(profiles_dir, name, "manifest")
        if os.path.isfile(manifest):
            entries = parse_manifest(open(manifest, encoding="utf-8").read())
            counts = {m: sum(1 for e in entries if e["mode"] == m)
                      for m in _MODES}
            out.append({"name": name, "entries": entries, "counts": counts})
    if not out:
        raise DotsError(f"no profiles found under {profiles_dir!r}")
    return out


def load_profile(profiles_dir, name):
    for profile in list_profiles(profiles_dir):
        if profile["name"] == name:
            return profile
    known = ", ".join(p["name"] for p in list_profiles(profiles_dir))
    raise DotsError(f"unknown profile {name!r} (known: {known})")


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def link_plan(entries, repo_dir, home):
    """Classify each link entry: create / replace / backup+replace / ok."""
    plan = []
    for entry in entries:
        if entry["mode"] != "link":
            continue
        src = os.path.join(repo_dir, entry["source"])
        dst = os.path.join(home, entry["target"])
        if not os.path.exists(src):
            raise DotsError(f"missing source in repo: {entry['source']!r}")
        if not os.path.lexists(dst):
            action = "create"
        elif os.path.islink(dst):
            action = "ok" if os.path.realpath(dst) == os.path.realpath(src) \
                else "replace"
        else:
            action = "backup+replace"   # real file in the way
        plan.append({"target": entry["target"], "source": entry["source"],
                     "action": action, "src": src, "dst": dst})
    return plan


def apply_links(plan, execute=False):
    """Side-effecting half of `link`; self_test only runs it in tempdirs."""
    applied = 0
    for item in plan:
        if item["action"] == "ok":
            continue
        if execute:
            if item["action"] == "replace" and os.path.islink(item["dst"]):
                os.unlink(item["dst"])
            os.makedirs(os.path.dirname(item["dst"]) or ".", exist_ok=True)
            os.symlink(item["src"], item["dst"])
        applied += 1
    return applied


def sync_plan(entries, repo_dir, home):
    """Copy-mode sync plan based on SHA-256 comparison."""
    plan = []
    for entry in entries:
        if entry["mode"] != "copy":
            continue
        src = os.path.join(repo_dir, entry["source"])
        dst = os.path.join(home, entry["target"])
        if not os.path.isfile(src):
            raise DotsError(f"missing source in repo: {entry['source']!r}")
        if not os.path.lexists(dst):
            plan.append({"target": entry["target"], "action": "copy",
                         "reason": "missing at destination"})
        elif os.path.islink(dst) or not os.path.isfile(dst):
            plan.append({"target": entry["target"], "action": "conflict",
                         "reason": "destination is not a regular file"})
        elif _sha(src) == _sha(dst):
            plan.append({"target": entry["target"], "action": "skip",
                         "reason": "identical"})
        else:
            plan.append({"target": entry["target"], "action": "copy",
                         "reason": "content differs"})
    return plan


def backup(entries, home, backup_dir, execute=False):
    """Back up current targets (files or symlinks) into backup_dir."""
    import shutil
    plan = []
    for entry in entries:
        dst = os.path.join(home, entry["target"])
        if not os.path.lexists(dst):
            continue
        saved = os.path.join(backup_dir, entry["target"])
        plan.append({"target": entry["target"], "saved": saved})
        if execute:
            os.makedirs(os.path.dirname(saved) or ".", exist_ok=True)
            if os.path.islink(dst):
                with open(saved + ".link", "w", encoding="utf-8") as fh:
                    fh.write(os.readlink(dst))
            else:
                shutil.copy2(dst, saved)
    return plan


def diff(entries, repo_dir, home):
    """Per-entry status: match / differ / missing / foreign."""
    report = []
    for entry in entries:
        src = os.path.join(repo_dir, entry["source"])
        dst = os.path.join(home, entry["target"])
        if not os.path.isfile(src):
            raise DotsError(f"missing source in repo: {entry['source']!r}")
        if not os.path.lexists(dst):
            status = "missing"
        elif entry["mode"] == "link":
            status = "match" if os.path.islink(dst) and \
                os.path.realpath(dst) == os.path.realpath(src) else "differ"
        elif not os.path.isfile(dst) or os.path.islink(dst):
            status = "foreign"
        else:
            status = "match" if _sha(src) == _sha(dst) else "differ"
        report.append({"target": entry["target"], "mode": entry["mode"],
                       "status": status})
    return report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=ENGINE["name"],
                                description=ENGINE["summary"])
    p.add_argument("--profiles", default=os.path.expanduser(
        "~/.config/sigma-dots/profiles"))
    p.add_argument("--profile", default="default")
    p.add_argument("--repo", default=None,
                   help="dotfiles repo root (default: profile dir)")
    p.add_argument("--home", default=os.path.expanduser("~"))
    sub = p.add_subparsers(dest="cmd", required=True)
    lk = sub.add_parser("link", help="symlink entries (dry run by default)")
    lk.add_argument("--execute", action="store_true")
    sub.add_parser("sync-plan", help="plan copying changed entries")
    bk = sub.add_parser("backup", help="back up current targets")
    bk.add_argument("--to", required=True)
    bk.add_argument("--execute", action="store_true")
    sub.add_parser("diff", help="compare repo vs installed state")
    pf = sub.add_parser("profile", help="list profiles or summarise one")
    pf.add_argument("--show", default=None, metavar="NAME")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "profile":
            if args.show:
                prof = load_profile(args.profiles, args.show)
                for entry in prof["entries"]:
                    print(f"{entry['mode']:<5} {entry['target']} "
                          f"<- {entry['source']}")
                return 0
            for prof in list_profiles(args.profiles):
                c = prof["counts"]
                print(f"{prof['name']:<16} link:{c['link']} copy:{c['copy']}")
            return 0
        profile = load_profile(args.profiles, args.profile)
        repo = args.repo or os.path.join(args.profiles, args.profile, "files")
        entries = profile["entries"]
        if args.cmd == "link":
            plan = link_plan(entries, repo, args.home)
            for item in plan:
                print(f"{item['action']:<14} {item['target']}")
            n = apply_links(plan, execute=args.execute)
            verb = "linked" if args.execute else "would link"
            print(f"{verb} {n} entry(ies)", file=sys.stderr)
        elif args.cmd == "sync-plan":
            for item in sync_plan(entries, repo, args.home):
                print(f"{item['action']:<8} {item['target']}  "
                      f"({item['reason']})")
        elif args.cmd == "backup":
            plan = backup(entries, args.home, args.to,
                          execute=args.execute)
            verb = "backed up" if args.execute else "would back up"
            print(f"{verb} {len(plan)} entry(ies) -> {args.to}",
                  file=sys.stderr)
            for item in plan:
                print(f"{item['target']} -> {item['saved']}")
        elif args.cmd == "diff":
            report = diff(entries, repo, args.home)
            for item in report:
                print(f"{item['status']:<8} {item['target']}")
            if any(i["status"] != "match" for i in report):
                return 1
        return 0
    except (DotsError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        # repo + profile + home fixture
        profiles = os.path.join(d, "profiles")
        prof_dir = os.path.join(profiles, "work")
        files = os.path.join(prof_dir, "files")
        os.makedirs(os.path.join(files, "config", "app"))
        home = os.path.join(d, "home")
        os.makedirs(home)
        with open(os.path.join(files, "bashrc"), "w") as fh:
            fh.write("export EDITOR=vim\n")
        with open(os.path.join(files, "config", "app", "conf"), "w") as fh:
            fh.write("color=blue\n")
        with open(os.path.join(prof_dir, "manifest"), "w") as fh:
            fh.write("# work profile\n"
                     "link .bashrc bashrc\n"
                     "copy .config/app/conf config/app/conf\n")
        # a second profile for listing
        srv = os.path.join(profiles, "server")
        os.makedirs(os.path.join(srv, "files"))
        with open(os.path.join(srv, "manifest"), "w") as fh:
            fh.write("link .bashrc\n")

        # manifest parsing
        entries = parse_manifest(
            "link .bashrc bashrc\ncopy .config/x\n# comment\n")
        assert entries == [{"mode": "link", "target": ".bashrc",
                            "source": "bashrc"},
                           {"mode": "copy", "target": ".config/x",
                            "source": ".config/x"}]
        for bad in ("exec .bashrc", "link /etc/passwd", "link ../up",
                    "link .bashrc a\nlink .bashrc b", "link",
                    "copy ok ok ok", "# empty\n"):
            try:
                parse_manifest(bad)
            except DotsError:
                pass
            else:
                raise AssertionError(f"manifest accepted: {bad!r}")

        # profiles
        names = [p["name"] for p in list_profiles(profiles)]
        assert names == ["server", "work"]
        work = load_profile(profiles, "work")
        assert work["counts"] == {"link": 1, "copy": 1}
        try:
            load_profile(profiles, "ghost")
        except DotsError:
            pass
        else:
            raise AssertionError("unknown profile accepted")

        # link plan + execute (inside the tempdir only)
        plan = link_plan(work["entries"], files, home)
        assert [i["action"] for i in plan] == ["create"]
        assert apply_links(plan, execute=False) == 1
        assert not os.path.lexists(os.path.join(home, ".bashrc"))
        assert apply_links(plan, execute=True) == 1
        assert os.path.islink(os.path.join(home, ".bashrc"))
        assert link_plan(work["entries"], files, home)[0]["action"] == "ok"
        # wrong symlink -> replace; regular file -> backup+replace
        os.unlink(os.path.join(home, ".bashrc"))
        os.symlink("/tmp/elsewhere", os.path.join(home, ".bashrc"))
        assert link_plan(work["entries"], files, home)[0]["action"] == \
            "replace"
        os.unlink(os.path.join(home, ".bashrc"))
        with open(os.path.join(home, ".bashrc"), "w") as fh:
            fh.write("handmade\n")
        assert link_plan(work["entries"], files, home)[0]["action"] == \
            "backup+replace"
        try:
            link_plan([{"mode": "link", "target": ".x", "source": "ghost"}],
                      files, home)
        except DotsError:
            pass
        else:
            raise AssertionError("missing repo source accepted")

        # sync plan
        splan = sync_plan(work["entries"], files, home)
        assert splan == [{"target": ".config/app/conf", "action": "copy",
                          "reason": "missing at destination"}]
        dst_conf = os.path.join(home, ".config", "app", "conf")
        os.makedirs(os.path.dirname(dst_conf))
        with open(dst_conf, "w") as fh:
            fh.write("color=blue\n")
        assert sync_plan(work["entries"], files, home)[0]["action"] == "skip"
        with open(dst_conf, "w") as fh:
            fh.write("color=red\n")
        assert sync_plan(work["entries"], files, home)[0] == {
            "target": ".config/app/conf", "action": "copy",
            "reason": "content differs"}
        os.unlink(dst_conf)
        os.symlink("/dev/null", dst_conf)
        assert sync_plan(work["entries"], files, home)[0]["action"] == \
            "conflict"
        os.unlink(dst_conf)

        # backup (execute inside tempdir)
        backup_dir = os.path.join(d, "backup")
        saved = backup(work["entries"], home, backup_dir, execute=True)
        assert [s["target"] for s in saved] == [".bashrc"]
        assert os.path.isfile(os.path.join(backup_dir, ".bashrc"))
        assert open(os.path.join(backup_dir, ".bashrc")).read() == \
            "handmade\n"
        os.unlink(os.path.join(home, ".bashrc"))
        os.symlink("/tmp/elsewhere", os.path.join(home, ".bashrc"))
        backup(work["entries"], home, backup_dir, execute=True)
        assert open(os.path.join(backup_dir, ".bashrc.link")).read() == \
            "/tmp/elsewhere"

        # diff
        report = {i["target"]: i["status"]
                  for i in diff(work["entries"], files, home)}
        assert report[".bashrc"] == "differ"     # symlink to foreign path
        assert report[".config/app/conf"] == "missing"
        apply_links(link_plan(work["entries"], files, home), execute=True)
        with open(dst_conf, "w") as fh:
            fh.write("color=blue\n")
        report = {i["target"]: i["status"]
                  for i in diff(work["entries"], files, home)}
        assert report[".bashrc"] == "match"
        assert report[".config/app/conf"] == "match"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
