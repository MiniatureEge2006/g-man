import inspect
import json
import os


def _extract_parameters(command):
    app_command = getattr(command, "app_command", None)

    if app_command is not None:
        if not hasattr(app_command, "parameters"):
            return []
        return [
            {
                "name": p.name,
                "description": p.description or "",
                "required": p.required,
                "type": p.type.name if hasattr(p.type, "name") else str(p.type),
            }
            for p in app_command.parameters
        ]

    params = []
    for name, param in command.clean_params.items():
        params.append(
            {
                "name": name,
                "description": "",
                "required": param.default is inspect.Parameter.empty,
                "type": getattr(param.annotation, "__name__", str(param.annotation)),
            }
        )
    return params


def generate_commands_json(bot, output_path):
    groups = {}
    for command in bot.walk_commands():
        if getattr(command, "hidden", False):
            continue
        cog_name = command.cog_name or "Uncategorized"
        is_group = hasattr(command, "commands") and bool(command.commands)
        groups.setdefault(cog_name, []).append(
            {
                "name": command.qualified_name,
                "description": command.help or command.description or "",
                "aliases": sorted(command.aliases),
                "parameters": _extract_parameters(command),
                "is_group": is_group,
            }
        )

    for category in groups:
        groups[category].sort(key=lambda c: c["name"])
    groups = dict(sorted(groups.items()))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(groups, f, indent=2, sort_keys=False)
        f.write("\n")


def generate_tags_json(bot, output_path):
    tags_cog = bot.get_cog("Tags")
    if tags_cog is None:
        return
    if not hasattr(tags_cog, "formatter"):
        return

    by_func = {}
    for name, func in tags_cog.formatter.functions.items():
        key = id(func)
        by_func.setdefault(key, {"names": [], "doc": inspect.getdoc(func) or ""})
        by_func[key]["names"].append(name)

    entries = []
    for data in by_func.values():
        names_sorted = sorted(data["names"], key=len)
        primary = names_sorted[0]
        aliases = names_sorted[1:]
        entries.append(
            {
                "name": primary,
                "aliases": aliases,
                "doc": data["doc"],
            }
        )
    entries.sort(key=lambda e: e["name"])

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def generate_gcoder_json(output_path):
    from cogs.code import SUPPORTED_LANGUAGES

    data = {
        "description": (
            "A sandboxed, Dockerized code execution service the bot talks to over HTTP "
            "for the code command, and that GScript can call into for scripting workflows."
        ),
        "languages": SUPPORTED_LANGUAGES,
        "endpoint": "http://localhost:8000/{language}/execute",
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def generate_site_data(bot, website_dir):
    generate_commands_json(bot, os.path.join(website_dir, "commands.json"))
    generate_tags_json(bot, os.path.join(website_dir, "tags.json"))
    generate_gcoder_json(os.path.join(website_dir, "gcoder.json"))
