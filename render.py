#!/usr/bin/env python

import sys
from argparse import ArgumentParser
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from datetime import datetime
from os import PathLike
from urllib.parse import quote, quote_plus
from toml import load
from shutil import copy
from babel.dates import format_date, format_datetime, format_time


class Entry:
    def __init__(
        self,
        title: str,
        description: str,
        tags: list[str],
        published: datetime,
        updated: datetime | None,
    ):
        self.title = title
        self.description = description
        self.tags = tags
        self.published = published
        self.updated = updated if updated is not None else published

    def __lt__(self, other):
        return self.published < other.published

    def __gt__(self, other):
        return self.published > other.published


if __name__ == "__main__":
    parser = ArgumentParser()

    parser.add_argument(
        "-c", "--catalog", "--catalog-file", default="catalog.toml", help="catalog file"
    )
    parser.add_argument(
        "-t", "--tag-tpl", "--tag-template", default="tag.html", help="tag template"
    )
    parser.add_argument(
        "-a", "--atom-tpl", "--atom-template", default="atom.xml", help="atom template"
    )
    parser.add_argument(
        "-m", "--meta-dir", "--meta-directory", default="meta", help="meta directory"
    )
    parser.add_argument(
        "-e",
        "--entries-dir",
        "--entries-directory",
        default="entries",
        help="entries directory",
    )
    parser.add_argument(
        "-p",
        "--pages-dir",
        "--pages-directory",
        default="pages",
        help="pages directory",
    )
    parser.add_argument(
        "-s",
        "--static-dir",
        "--static-directory",
        default="static",
        help="static directory",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        "--output-directory",
        default="output",
        help="output directory",
    )
    parser.add_argument("-f", "--force", action="store_true", help="overwrite files")
    parser.add_argument(
        "-d", "--delete", action="store_true", help="delete remaining files"
    )

    args = parser.parse_args(sys.argv[1:])

    all_tags = []
    entries = {}
    catalog = load(args.catalog)
    for identifier in catalog:
        raw_entry = catalog[identifier]

        if raw_entry.keys() > {"title", "description", "tags", "published", "updated"}:
            raise KeyError("Unsupported parameter(s)")

        entries[identifier] = Entry(
            title=raw_entry["title"],
            description=raw_entry["description"],
            tags=raw_entry["tags"] if "tags" in raw_entry else [],
            published=raw_entry["published"],
            updated=raw_entry.get("updated", None)
        )

        for tag in raw_entry["tags"]:
            if tag not in all_tags:
                all_tags.append(tag)

    for dir in [args.meta_dir, args.entries_dir, args.pages_dir, args.output_dir]:
        resolved = Path(dir).resolve()
        if resolved.exists() and not resolved.is_dir():
            raise NotADirectoryError

    env = Environment(
        loader=FileSystemLoader(
            [
                args.meta_dir,
                args.entries_dir,
                args.pages_dir,
                args.tag_tpl,
                args.atom_tpl,
            ]
        ),
        autoescape=True,
    )

    env.globals.update(
        format_date=format_date,
        format_datetime=format_datetime,
        format_time=format_time,
        locale="en",
        now=datetime.now(),
        all_tags=all_tags,
    )

    env.filters["url_quote"] = lambda s: quote(s)
    env.filters["url_quote_plus"] = lambda s: quote_plus(s)

    written_files: list[str | PathLike] = []

    def is_written(file: str | PathLike) -> bool:
        file = Path(file)
        for written_file in written_files:
            if Path(written_file).samefile(file):
                return True
        return False

    def skip_unchanged(file: str | PathLike) -> bool:
        file = Path(file)
        if file.exists() and (is_written(file) or not args.force):
            if not is_written(file) and not args.force:
                written_files.append(file.resolve())
            return True
        else:
            return False

    def mark_written(file: str | PathLike) -> None:
        file = Path(file)
        written_files.append(file.resolve())

    for src_file in Path(args.pages_dir).rglob("*"):
        if src_file.is_file():
            dest_file = Path(args.output_dir) / src_file.relative_to(args.pages_dir)

            if skip_unchanged(dest_file):
                continue

            dest_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.write_text(
                env.get_template(str(src_file.relative_to(args.pages_dir))).render(
                    src_file=src_file, entries=entries
                )
            )
            mark_written(dest_file)

    for src_file in entries:
        entry = entries[src_file]

        dest_file = Path(args.output_dir) / "entries" / src_file

        if skip_unchanged(dest_file):
            continue

        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_text(
            env.get_template(str(src_file)).render(
                src_file=Path(src_file),
                entries=entries,
                title=entry.title,
                description=entry.description,
                tags=entry.tags,
                published=entry.published,
                updated=entry.updated,
            )
        )
        mark_written(dest_file)

    for tag in all_tags:
        src_file = str(args.tag_tpl)
        dest_file = (Path(args.output_dir) / "tags" / tag).with_suffix(".html")

        if skip_unchanged(dest_file):
            continue

        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_text(
            env.get_template(src_file).render(
                src_file=Path(src_file),
                entries=dict(
                    filter(lambda entry: tag in entry[1].tags, entries.items())
                ),
                tag=tag,
            )
        )
        mark_written(dest_file)

    for src_file in Path(args.static_dir).rglob("*"):
        if src_file.is_file():
            dest_file = Path(args.output_dir) / src_file.relative_to(args.static_dir)

            if skip_unchanged(dest_file):
                continue

            dest_file.parent.mkdir(parents=True, exist_ok=True)
            copy(src_file, dest_file)
            mark_written(dest_file)

    dest_file = Path(args.output_dir) / "atom.xml"
    if not skip_unchanged(dest_file):
        dest_file.parent.mkdir(parents=True, exist_ok=True)

        latest = None
        for src_file, entry in entries.items():
            if latest is None or entry.updated > latest:
                latest = entry.updated

        src_file = str(args.atom_tpl)

        dest_file.write_text(
            env.get_template(src_file).render(
                entries=entries,
                latest=latest
            )
        )
        mark_written(dest_file)

    if args.delete:
        for file in Path(args.output_dir).rglob("*"):
            if file.is_file():
                resolved = file.resolve()
                if not is_written(file):
                    resolved.unlink()
