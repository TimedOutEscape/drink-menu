import json
import os
import re
import subprocess
import uuid
import shutil
import tempfile

from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data", "menu.json")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
STATIC_PAGE_BRANCH = "static-page"
STATIC_PAGE_WORKTREE = os.path.join(tempfile.gettempdir(), "toe-menu-static-page")
STATIC_EXPORT_ASSETS_DIR = os.path.join(STATIC_PAGE_WORKTREE, "assets")

app = Flask(__name__)


def _git_run(args, cwd=BASE_DIR):
    return subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _ensure_static_page_worktree():
    git_dir = os.path.join(STATIC_PAGE_WORKTREE, ".git")
    if os.path.exists(git_dir):
        return

    if os.path.isdir(STATIC_PAGE_WORKTREE):
        shutil.rmtree(STATIC_PAGE_WORKTREE)

    os.makedirs(os.path.dirname(STATIC_PAGE_WORKTREE), exist_ok=True)
    branch_exists = bool(_git_run(["git", "branch", "--list", STATIC_PAGE_BRANCH]).stdout.strip())
    if branch_exists:
        result = _git_run(["git", "worktree", "add", STATIC_PAGE_WORKTREE, STATIC_PAGE_BRANCH])
    else:
        result = _git_run(["git", "worktree", "add", "-b", STATIC_PAGE_BRANCH, STATIC_PAGE_WORKTREE, "HEAD"])

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to create static-page worktree")


def _remove_path(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)


def _copy_static_file(relative_path):
    source_path = os.path.join(BASE_DIR, relative_path)
    destination_path = os.path.join(STATIC_PAGE_WORKTREE, relative_path)
    if os.path.exists(source_path):
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        shutil.copy2(source_path, destination_path)


def _read_text_file(relative_path):
    with open(os.path.join(BASE_DIR, relative_path), "r", encoding="utf-8") as file:
        return file.read()


def _build_static_page_html(data):
    html = render_template("web.html", data=data)
    css = _read_text_file(os.path.join("static", "web.css"))
    js = _read_text_file(os.path.join("static", "web.js"))

    html = html.replace(
        '<link rel="stylesheet" href="/static/web.css">',
        f"<style>\n{css}\n</style>",
    )
    html = html.replace(
        '<script src="/static/web.js"></script>',
        f"<script>\n{js}\n</script>",
    )
    html = html.replace("/static/img/timed-out-logo.png", "assets/timed-out-logo.png")
    html = html.replace("/static/uploads/", "assets/uploads/")
    return html


def publish_static_site():
    try:
        data = load_data()
        _ensure_static_page_worktree()

        for entry in os.listdir(STATIC_PAGE_WORKTREE):
            if entry == ".git":
                continue
            _remove_path(os.path.join(STATIC_PAGE_WORKTREE, entry))

        index_path = os.path.join(STATIC_PAGE_WORKTREE, "index.html")
        with open(index_path, "w", encoding="utf-8") as file:
            file.write(_build_static_page_html(data))

        for relative_path in (
            "static/img/timed-out-logo.png",
            "static/img/drinkmenu-qr.png",
        ):
            source_path = os.path.join(BASE_DIR, relative_path)
            destination_path = os.path.join(STATIC_EXPORT_ASSETS_DIR, os.path.basename(relative_path))
            if os.path.exists(source_path):
                os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                shutil.copy2(source_path, destination_path)

        uploads_source = os.path.join(BASE_DIR, "static", "uploads")
        uploads_destination = os.path.join(STATIC_EXPORT_ASSETS_DIR, "uploads")
        if os.path.isdir(uploads_source):
            os.makedirs(uploads_destination, exist_ok=True)
            for filename in os.listdir(uploads_source):
                source_path = os.path.join(uploads_source, filename)
                if os.path.isfile(source_path):
                    shutil.copy2(source_path, os.path.join(uploads_destination, filename))

        _git_run(["git", "add", "-A"], cwd=STATIC_PAGE_WORKTREE)
        status = _git_run(["git", "status", "--porcelain"], cwd=STATIC_PAGE_WORKTREE)
        if not status.stdout.strip():
            return

        _git_run(["git", "commit", "-m", "auto: update static web menu"], cwd=STATIC_PAGE_WORKTREE)
        _git_run(["git", "push", "-u", "origin", STATIC_PAGE_BRANCH], cwd=STATIC_PAGE_WORKTREE)
    except Exception as exc:
        print(f"Static page publish failed: {exc}")


def commit_and_push(message):
    safe_message = re.sub(r"\s+", " ", (message or "updated menu")).strip()
    if not safe_message:
        safe_message = "updated menu"
    safe_message = f"auto: {safe_message}"

    publish_static_site()
    _git_run(["git", "add", "-A"])
    status = _git_run(["git", "status", "--porcelain"])
    if not status.stdout.strip():
        return

    _git_run(["git", "commit", "-m", safe_message])
    _git_run(["git", "push"])

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