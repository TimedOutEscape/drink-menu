import json
import base64
from datetime import datetime, timezone
import os
import re
import subprocess
import uuid
import shutil
import tempfile
import logging

from flask import Flask, jsonify, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data", "menu.json")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
STATIC_PAGE_BRANCH = "static-page"
STATIC_PAGE_WORKTREE_FALLBACK = os.path.join(os.path.dirname(BASE_DIR), ".toe-menu-static-page-worktree")
STATIC_PAGE_PRESERVED_FILES = {"CNAME", "README", "README.md"}
GIT_COMMAND_TIMEOUT = 60
GIT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
}

app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app.logger.setLevel(logging.INFO)
logging.getLogger("werkzeug").setLevel(logging.WARNING)


def _log_git(message):
    app.logger.info("[git] %s", message)


def _git_run(args, cwd=BASE_DIR):
    try:
        _log_git(f"running {' '.join(args)} in {cwd}")
        return subprocess.run(
            args,
            cwd=cwd,
            env={**os.environ, **GIT_ENV},
            timeout=GIT_COMMAND_TIMEOUT,
            check=False,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Git command timed out after {GIT_COMMAND_TIMEOUT}s: {' '.join(args)}") from exc


def _git_run_with_env(args, cwd=BASE_DIR, extra_env=None):
    env = {**os.environ, **GIT_ENV}
    if extra_env:
        env.update(extra_env)
    try:
        _log_git(f"running {' '.join(args)} in {cwd} with env overrides {sorted((extra_env or {}).keys())}")
        return subprocess.run(
            args,
            cwd=cwd,
            env=env,
            timeout=GIT_COMMAND_TIMEOUT,
            check=False,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Git command timed out after {GIT_COMMAND_TIMEOUT}s: {' '.join(args)}") from exc


def _get_static_page_worktree_path():
    result = _git_run(["git", "worktree", "list", "--porcelain"])
    current_worktree = None
    current_branch = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_worktree = line.removeprefix("worktree ").strip()
        elif line.startswith("branch "):
            current_branch = line.removeprefix("branch ").strip()
        elif line == "":
            if (
                current_branch == f"refs/heads/{STATIC_PAGE_BRANCH}"
                and current_worktree
                and os.path.exists(os.path.join(current_worktree, ".git"))
            ):
                return current_worktree
            current_worktree = None
            current_branch = None

    if (
        current_branch == f"refs/heads/{STATIC_PAGE_BRANCH}"
        and current_worktree
        and os.path.exists(os.path.join(current_worktree, ".git"))
    ):
        return current_worktree

    return STATIC_PAGE_WORKTREE_FALLBACK


def _ensure_static_page_worktree():
    _log_git("pruning stale worktrees")
    _git_run(["git", "worktree", "prune"])
    static_page_worktree = _get_static_page_worktree_path()
    if os.path.exists(os.path.join(static_page_worktree, ".git")):
        return

    if os.path.isdir(static_page_worktree):
        shutil.rmtree(static_page_worktree)

    os.makedirs(os.path.dirname(static_page_worktree), exist_ok=True)
    branch_exists = bool(_git_run(["git", "branch", "--list", STATIC_PAGE_BRANCH]).stdout.strip())
    if branch_exists:
        _log_git(f"adding existing branch worktree for {STATIC_PAGE_BRANCH} at {static_page_worktree}")
        result = _git_run(["git", "worktree", "add", static_page_worktree, STATIC_PAGE_BRANCH])
    else:
        _log_git(f"creating new branch worktree for {STATIC_PAGE_BRANCH} at {static_page_worktree}")
        result = _git_run(["git", "worktree", "add", "-b", STATIC_PAGE_BRANCH, static_page_worktree, "HEAD"])

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to create static-page worktree")


def _remove_path(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)


def _copy_static_file(relative_path):
    source_path = os.path.join(BASE_DIR, relative_path)
    destination_path = os.path.join(_get_static_page_worktree_path(), relative_path)
    if os.path.exists(source_path):
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        shutil.copy2(source_path, destination_path)


def _read_text_file(relative_path):
    with open(os.path.join(BASE_DIR, relative_path), "r", encoding="utf-8") as file:
        return file.read()


def _read_binary_file(relative_path):
    with open(os.path.join(BASE_DIR, relative_path), "rb") as file:
        return file.read()


def _image_data_uri(relative_path):
    ext = os.path.splitext(relative_path)[1].lower().lstrip(".") or "png"
    encoded = base64.b64encode(_read_binary_file(relative_path)).decode("ascii")
    return f"data:image/{ext};base64,{encoded}"


def _build_static_page_html(data):
    with app.test_request_context("/"):
        html = render_template("web.html", data=data)
    css = _read_text_file(os.path.join("static", "web.css"))
    js = _read_text_file(os.path.join("static", "web.js"))

    html = html.replace(
        '<link rel="stylesheet" href="/static/web.css">',
        f"<style>\n{css}\n</style>",
    )
    html = html.replace(
        '<link rel="icon" type="image/png" href="/static/img/favicon.png">',
        f'<link rel="icon" type="image/png" href="{_image_data_uri(os.path.join("static", "img", "favicon.png"))}">',
    )
    html = html.replace(
        '<script src="/static/web.js"></script>',
        f"<script>\n{js}\n</script>",
    )
    html = html.replace("/static/img/timed-out-logo.png", "assets/timed-out-logo.png")
    html = html.replace("/static/uploads/", "assets/uploads/")
    return html


def publish_static_site(commit_message):
    try:
        _log_git(f"publishing static site with commit message: {commit_message}")
        data = load_data()
        _ensure_static_page_worktree()
        static_page_worktree = _get_static_page_worktree_path()
        static_export_assets_dir = os.path.join(static_page_worktree, "assets")

        for entry in os.listdir(static_page_worktree):
            if entry == ".git" or entry in STATIC_PAGE_PRESERVED_FILES:
                continue
            _remove_path(os.path.join(static_page_worktree, entry))

        index_path = os.path.join(static_page_worktree, "index.html")
        with open(index_path, "w", encoding="utf-8") as file:
            file.write(_build_static_page_html(data))

        for relative_path in (
            "static/img/timed-out-logo.png",
            "static/img/drinkmenu-qr.png",
        ):
            source_path = os.path.join(BASE_DIR, relative_path)
            if os.path.exists(source_path):
                root_destination_path = os.path.join(static_page_worktree, os.path.basename(relative_path))
                shutil.copy2(source_path, root_destination_path)
                if os.path.basename(relative_path) != "favicon.png":
                    destination_path = os.path.join(static_export_assets_dir, os.path.basename(relative_path))
                    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                    shutil.copy2(source_path, destination_path)

        uploads_source = os.path.join(BASE_DIR, "static", "uploads")
        uploads_destination = os.path.join(static_export_assets_dir, "uploads")
        if os.path.isdir(uploads_source):
            os.makedirs(uploads_destination, exist_ok=True)
            for filename in os.listdir(uploads_source):
                source_path = os.path.join(uploads_source, filename)
                if os.path.isfile(source_path):
                    shutil.copy2(source_path, os.path.join(uploads_destination, filename))

        _git_run(["git", "add", "-A"], cwd=static_page_worktree)
        status = _git_run(["git", "status", "--porcelain"], cwd=static_page_worktree)
        if not status.stdout.strip():
            return

        _git_run(["git", "commit", "-m", commit_message], cwd=static_page_worktree)
        _git_run(["git", "push", "--force", "-u", "origin", STATIC_PAGE_BRANCH], cwd=static_page_worktree)
        _ensure_static_page_upstream(static_page_worktree)
    except Exception as exc:
        print(f"Static page publish failed: {exc}")


def _get_commit_timestamp(commit_hash, cwd):
    result = _git_run(["git", "show", "-s", "--format=%cI", commit_hash], cwd=cwd)
    timestamp = result.stdout.strip()
    if not timestamp:
        raise RuntimeError("Could not read commit timestamp")
    return timestamp


def _get_remote_branch_hash(cwd, branch):
    result = _git_run(["git", "ls-remote", "origin", f"refs/heads/{branch}"], cwd=cwd)
    reference = result.stdout.strip()
    if not reference:
        raise RuntimeError(f"Remote branch {branch} was not found after push")
    return reference.split()[0]


def _ensure_static_page_upstream(static_page_worktree):
    expected_upstream = f"origin/{STATIC_PAGE_BRANCH}"
    result = _git_run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=static_page_worktree)
    current_upstream = result.stdout.strip() if result.returncode == 0 else ""
    if current_upstream == expected_upstream:
        _log_git(f"upstream for {STATIC_PAGE_BRANCH} already configured as {expected_upstream}")
        return

    _log_git(f"setting upstream for {STATIC_PAGE_BRANCH} to {expected_upstream}")
    set_result = _git_run(["git", "branch", "--set-upstream-to", expected_upstream, STATIC_PAGE_BRANCH], cwd=static_page_worktree)
    if set_result.returncode != 0:
        raise RuntimeError(set_result.stderr.strip() or set_result.stdout.strip() or f"Failed to set upstream for {STATIC_PAGE_BRANCH}")


def export_static_site(manual=False):
    data = load_data()
    _ensure_static_page_worktree()
    static_page_worktree = _get_static_page_worktree_path()
    static_export_assets_dir = os.path.join(static_page_worktree, "assets")

    for entry in os.listdir(static_page_worktree):
        if entry == ".git" or entry in STATIC_PAGE_PRESERVED_FILES:
            continue
        _remove_path(os.path.join(static_page_worktree, entry))

    index_path = os.path.join(static_page_worktree, "index.html")
    with open(index_path, "w", encoding="utf-8") as file:
        file.write(_build_static_page_html(data))

    for relative_path in (
        "static/img/timed-out-logo.png",
        "static/img/drinkmenu-qr.png",
    ):
        source_path = os.path.join(BASE_DIR, relative_path)
        if os.path.exists(source_path):
            root_destination_path = os.path.join(static_page_worktree, os.path.basename(relative_path))
            shutil.copy2(source_path, root_destination_path)
            if os.path.basename(relative_path) != "favicon.png":
                destination_path = os.path.join(static_export_assets_dir, os.path.basename(relative_path))
                os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                shutil.copy2(source_path, destination_path)

    uploads_source = os.path.join(BASE_DIR, "static", "uploads")
    uploads_destination = os.path.join(static_export_assets_dir, "uploads")
    if os.path.isdir(uploads_source):
        os.makedirs(uploads_destination, exist_ok=True)
        for filename in os.listdir(uploads_source):
            source_path = os.path.join(uploads_source, filename)
            if os.path.isfile(source_path):
                shutil.copy2(source_path, os.path.join(uploads_destination, filename))

    _git_run(["git", "add", "-A"], cwd=static_page_worktree)

    commit_message = "manual public site export" if manual else "auto public site export"
    commit_timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    commit_env = {
        "GIT_AUTHOR_DATE": commit_timestamp,
        "GIT_COMMITTER_DATE": commit_timestamp,
    }
    commit_args = ["git", "commit", "--allow-empty", "-m", commit_message]
    if not manual:
        status = _git_run(["git", "status", "--porcelain"], cwd=static_page_worktree)
        if status.stdout.strip():
            commit_args = ["git", "commit", "-m", commit_message]
            commit_env = None

    _log_git(f"creating export commit at {commit_timestamp}")
    commit_result = _git_run_with_env(commit_args, cwd=static_page_worktree, extra_env=commit_env)
    if commit_result.returncode != 0:
        raise RuntimeError(commit_result.stderr.strip() or commit_result.stdout.strip() or "Failed to commit static page export")

    commit_hash = _git_run(["git", "rev-parse", "HEAD"], cwd=static_page_worktree).stdout.strip()
    if not commit_hash:
        raise RuntimeError("Could not determine the static page commit hash")

    actual_commit_timestamp = _get_commit_timestamp(commit_hash, static_page_worktree)
    if manual and actual_commit_timestamp != commit_timestamp:
        raise RuntimeError("The static page export commit timestamp did not match the manual export timestamp")

    _log_git(f"pushing static-page commit {commit_hash}")
    _git_run(["git", "push", "--force", "-u", "origin", STATIC_PAGE_BRANCH], cwd=static_page_worktree)
    _ensure_static_page_upstream(static_page_worktree)
    _log_git(f"verifying remote branch tip for {STATIC_PAGE_BRANCH}")
    remote_hash = _get_remote_branch_hash(static_page_worktree, STATIC_PAGE_BRANCH)
    if remote_hash != commit_hash:
        raise RuntimeError("The static page branch push did not land on the expected commit")

    return {
        "commit_hash": commit_hash,
        "commit_timestamp": actual_commit_timestamp,
        "branch": STATIC_PAGE_BRANCH,
    }


def commit_and_push(message):
    safe_message = re.sub(r"\s+", " ", (message or "updated menu")).strip()
    if not safe_message:
        safe_message = "updated menu"
    safe_message = f"auto: {safe_message}"

    publish_static_site(safe_message)
    _git_run(["git", "add", "-A"])
    status = _git_run(["git", "status", "--porcelain"])
    if not status.stdout.strip():
        return

    _git_run(["git", "commit", "-m", safe_message])
    _git_run(["git", "push"])


@app.route("/export-static-page", methods=["POST"])
def export_static_page():
    try:
        result = export_static_site(manual=True)
        return jsonify({
            "ok": True,
            "message": f"Public site updated and pushed to {result['branch']} at {result['commit_timestamp']}",
            "commit_hash": result["commit_hash"],
            "commit_timestamp": result["commit_timestamp"],
        })
    except Exception as exc:
        app.logger.exception("Manual export failed")
        return jsonify({"ok": False, "message": str(exc)}), 500

def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


app.jinja_env.filters["slugify"] = slugify

DEFAULT_DATA = {
    "title": "Our Drink Menu",
    "sections": [],
}


def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA)
        return json.loads(json.dumps(DEFAULT_DATA))
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def new_id():
    return uuid.uuid4().hex[:8]


def find_section(data, section_id):
    for s in data["sections"]:
        if s["id"] == section_id:
            return s
    return None


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


@app.route("/")
def admin():
    data = load_data()
    return render_template("admin.html", data=data)


@app.route("/menu")
def menu():
    data = load_data()
    return render_template("menu.html", data=data)


@app.route("/web")
def web_menu():
    data = load_data()
    return render_template("web.html", data=data)


@app.route("/title", methods=["POST"])
def update_title():
    data = load_data()
    title = request.form.get("title", "").strip()
    if title and title != data.get("title"):
        data["title"] = title
        save_data(data)
        commit_and_push(f"changed title to {title}")
    return redirect(url_for("admin"))


@app.route("/sections/add", methods=["POST"])
def add_section():
    data = load_data()
    name = request.form.get("name", "").strip()
    if name:
        data["sections"].append({"id": new_id(), "name": name, "drinks": []})
        save_data(data)
        commit_and_push(f"added section {name}")
    return redirect(url_for("admin"))


@app.route("/sections/<section_id>/rename", methods=["POST"])
def rename_section(section_id):
    data = load_data()
    section = find_section(data, section_id)
    name = request.form.get("name", "").strip()
    if section and name and name != section.get("name"):
        section["name"] = name
        save_data(data)
        commit_and_push(f"renamed section to {name}")
    return redirect(url_for("admin"))


@app.route("/sections/<section_id>/delete", methods=["POST"])
def delete_section(section_id):
    data = load_data()
    section = find_section(data, section_id)
    data["sections"] = [s for s in data["sections"] if s["id"] != section_id]
    if section:
        save_data(data)
        commit_and_push(f"deleted section {section.get('name', section_id)}")
    return redirect(url_for("admin"))


@app.route("/sections/<section_id>/move", methods=["POST"])
def move_section(section_id):
    data = load_data()
    sections = data["sections"]
    idx = next((i for i, s in enumerate(sections) if s["id"] == section_id), None)
    direction = request.form.get("direction")
    if idx is not None:
        new_idx = idx - 1 if direction == "up" else idx + 1
        if 0 <= new_idx < len(sections):
            sections[idx], sections[new_idx] = sections[new_idx], sections[idx]
            save_data(data)
            moved_name = sections[new_idx].get("name", "section")
            commit_and_push(f"reordered section {moved_name}")
    return redirect(url_for("admin"))


def save_drink_image(file):
    ext = file.filename.rsplit(".", 1)[1].lower()
    filename = f"label_{new_id()}.{ext}"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file.save(os.path.join(UPLOAD_DIR, secure_filename(filename)))
    return filename


def delete_drink_image(filename):
    if filename:
        path = os.path.join(UPLOAD_DIR, filename)
        if os.path.exists(path):
            os.remove(path)


@app.route("/sections/<section_id>/drinks/add", methods=["POST"])
def add_drink(section_id):
    data = load_data()
    section = find_section(data, section_id)
    name = request.form.get("name", "").strip()
    if section and name:
        drink = {
            "id": new_id(),
            "name": name,
            "price": request.form.get("price", "").strip(),
            "description": request.form.get("description", "").strip(),
            "extended_description": request.form.get("extended_description", "").strip(),
            "image": None,
        }
        file = request.files.get("image")
        if file and file.filename and allowed_file(file.filename):
            drink["image"] = save_drink_image(file)
        section["drinks"].append(drink)
        save_data(data)
        if drink["image"]:
            commit_and_push(f"added picture to {name}")
        else:
            commit_and_push(f"added {name}")
    return redirect(url_for("admin"))


@app.route("/sections/<section_id>/drinks/<drink_id>/update", methods=["POST"])
def update_drink(section_id, drink_id):
    data = load_data()
    section = find_section(data, section_id)
    if section:
        for d in section["drinks"]:
            if d["id"] == drink_id:
                old_name = d.get("name", "drink")
                old_price = d.get("price", "")
                old_description = d.get("description", "")
                old_extended_description = d.get("extended_description", "")
                old_image = d.get("image")
                d["name"] = request.form.get("name", "").strip() or d["name"]
                d["price"] = request.form.get("price", "").strip()
                d["description"] = request.form.get("description", "").strip()
                d["extended_description"] = request.form.get("extended_description", "").strip()
                if request.form.get("remove_image"):
                    delete_drink_image(d.get("image"))
                    d["image"] = None
                file = request.files.get("image")
                if file and file.filename and allowed_file(file.filename):
                    delete_drink_image(d.get("image"))
                    d["image"] = save_drink_image(file)
                changed = (
                    d.get("name") != old_name
                    or d.get("price") != old_price
                    or d.get("description") != old_description
                    or d.get("extended_description") != old_extended_description
                    or d.get("image") != old_image
                )
                if changed:
                    save_data(data)
                    drink_name = d.get("name", old_name)
                    if old_image != d.get("image") and d.get("image"):
                        commit_and_push(f"added picture to {drink_name}")
                    elif old_image and not d.get("image"):
                        commit_and_push(f"removed picture from {drink_name}")
                    elif drink_name != old_name:
                        commit_and_push(f"changed {old_name} to {drink_name}")
                    else:
                        commit_and_push(f"changed {drink_name}")
                break
    return redirect(url_for("admin"))


@app.route("/sections/<section_id>/drinks/<drink_id>/delete", methods=["POST"])
def delete_drink(section_id, drink_id):
    data = load_data()
    section = find_section(data, section_id)
    if section:
        deleted_name = None
        for d in section["drinks"]:
            if d["id"] == drink_id:
                deleted_name = d.get("name", "drink")
                delete_drink_image(d.get("image"))
                break
        section["drinks"] = [d for d in section["drinks"] if d["id"] != drink_id]
        if deleted_name:
            save_data(data)
            commit_and_push(f"deleted {deleted_name}")
    return redirect(url_for("admin"))


@app.route("/sections/<section_id>/drinks/<drink_id>/move", methods=["POST"])
def move_drink(section_id, drink_id):
    data = load_data()
    section = find_section(data, section_id)
    direction = request.form.get("direction")
    if section:
        drinks = section["drinks"]
        idx = next((i for i, d in enumerate(drinks) if d["id"] == drink_id), None)
        if idx is not None:
            new_idx = idx - 1 if direction == "up" else idx + 1
            if 0 <= new_idx < len(drinks):
                drinks[idx], drinks[new_idx] = drinks[new_idx], drinks[idx]
                save_data(data)
                moved_name = drinks[new_idx].get("name", "drink")
                commit_and_push(f"reordered {moved_name}")
    return redirect(url_for("admin"))


if __name__ == "__main__":
    app.run(debug=True, port=5050, host="0.0.0.0")