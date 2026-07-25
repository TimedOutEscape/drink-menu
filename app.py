import json
import os
import re
import subprocess
import uuid

from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data", "menu.json")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__)


def _git_run(args):
    return subprocess.run(
        args,
        cwd=BASE_DIR,
        check=False,
        capture_output=True,
        text=True,
    )


def commit_and_push(message):
    safe_message = re.sub(r"\s+", " ", (message or "updated menu")).strip()
    if not safe_message:
        safe_message = "updated menu"
    safe_message = f"auto: {safe_message}"

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