#!/usr/bin/env python3
"""Turn the interview guides into data the study app can show.

Content fidelity rule: this script CONVERTS markdown to HTML with pandoc and
copies the result. It never rewrites, summarises or generates text. The only
edits made to the converted HTML are:
  * rewriting <img src> to point at the copied figures
  * adding CSS class attributes so the UI can style the standard zones

Run:  python build.py
"""

import html as htmllib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from config import GUIDES, LONG_ANSWER_WORDS, OUT_ROOT, SOURCE_ROOT

# --wrap=none is mandatory. Pandoc's default 72-column wrapping splits HTML
# attributes across lines, which hides section ids from the parser below.
PANDOC = ["pandoc", "--section-divs", "--mathml", "--wrap=none",
          "-f", "markdown", "-t", "html5"]

HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
PART_META = re.compile(r"<!--\s*part:\s*(.*?)\s*-->", re.DOTALL)
SECTION_TOKEN = re.compile(r"<section\b[^>]*>|</section>", re.IGNORECASE)
ATTR_ID = re.compile(r'id="([^"]*)"')
ATTR_CLASS = re.compile(r'class="([^"]*)"')
FIRST_H3 = re.compile(r"<h3\b[^>]*>(.*?)</h3>", re.DOTALL | re.IGNORECASE)
QNUM = re.compile(r"^\s*(Q\d+\.\d+\w*)[.:\s]\s*(.*)$", re.DOTALL)
IMG_SRC = re.compile(r'(<img\b[^>]*\bsrc=")([^"]+)(")', re.IGNORECASE)
TAGS = re.compile(r"<[^>]+>")
MD_QUESTION_LINE = re.compile(r"^### Q", re.MULTILINE)
HEADING_H1 = re.compile(r"^# +(.*)$", re.MULTILINE)
HEADING_H2 = re.compile(r"^## +(.*)$", re.MULTILINE)


class BuildError(Exception):
    pass


def strip_tags(fragment):
    """Visible text of an HTML fragment, for search and word counts."""
    without_math = re.sub(r"<math\b.*?</math>", " ", fragment,
                          flags=re.DOTALL | re.IGNORECASE)
    return htmllib.unescape(TAGS.sub(" ", without_math))


def run_pandoc(markdown_text, where):
    result = subprocess.run(PANDOC, input=markdown_text.encode("utf-8"),
                            capture_output=True)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace")
        raise BuildError("pandoc failed on " + where + ": " + detail)
    return result.stdout.decode("utf-8")


def parse_sections(doc):
    """Every <section> in the document, in the order they open.

    Pandoc's --section-divs output is well formed, so matching open and close
    tokens with a stack is reliable. Each node carries its inner HTML, which
    includes its own heading.
    """
    nodes, stack = [], []
    for match in SECTION_TOKEN.finditer(doc):
        token = match.group(0)
        if token.startswith("</"):
            if stack:
                node = stack.pop()
                node["inner"] = doc[node["inner_start"]:match.start()]
                nodes.append(node)
        else:
            sid = ATTR_ID.search(token)
            cls = ATTR_CLASS.search(token)
            stack.append({
                "id": sid.group(1) if sid else "",
                "cls": cls.group(1) if cls else "",
                "order": match.start(),
                "inner_start": match.end(),
            })
    if stack:
        raise BuildError("unbalanced <section> tags in pandoc output")
    nodes.sort(key=lambda n: n["order"])
    return nodes


def style_zones(answer_html):
    """Tag the three zones every answer in these guides uses.

    Adds class attributes only. No text is changed.
    """
    answer_html = re.sub(
        r"<p><strong>In one line:</strong>",
        '<p class="one-liner"><strong>In one line:</strong>',
        answer_html, count=1)

    def tag_quote(match):
        inner = match.group(1)
        if "Likely follow-up" in inner or "Likely follow up" in inner:
            return '<blockquote class="followup">' + inner + "</blockquote>"
        return match.group(0)

    return re.sub(r"<blockquote>(.*?)</blockquote>", tag_quote, answer_html,
                  flags=re.DOTALL)


def resolve_figure(src, section_file, guide_root):
    """Figure paths use two conventions in these guides.

    ML-Stats writes 'figures/x.png' relative to the guide root; Forecasting
    writes '../images/x.png' relative to the sections folder. Try the section
    file's own directory first, then the guide root.
    """
    for base in (section_file.parent, guide_root):
        candidate = (base / src).resolve()
        if candidate.is_file():
            return candidate
    return None


def rewrite_figures(fragment, section_file, guide_root, guide_key,
                    figures_out, owner_id, problems):
    """Copy every referenced figure into the app and repoint the src at it.

    Returns the edited HTML and the list of app-relative figure paths.
    """
    found = []
    guide_figures = figures_out / guide_key

    def rewrite(match):
        src = match.group(2)
        if src.startswith(("http://", "https://", "data:")):
            return match.group(0)
        resolved = resolve_figure(src, section_file, guide_root)
        if resolved is None:
            problems.append(owner_id + ": figure not found: " + src)
            return match.group(0)
        guide_figures.mkdir(parents=True, exist_ok=True)
        target = guide_figures / resolved.name
        if not target.exists():
            shutil.copy2(resolved, target)
        rel = "figures/" + guide_key + "/" + resolved.name
        found.append(rel)
        return match.group(1) + rel + match.group(3)

    return IMG_SRC.sub(rewrite, fragment), found


def build_guide(guide, figures_out, problems):
    guide_root = SOURCE_ROOT / guide["dir"]
    sections_dir = guide_root / guide["sections"]
    if not sections_dir.is_dir():
        raise BuildError("no sections folder: " + str(sections_dir))

    excluded = set(guide["exclude"])
    section_files = sorted(p for p in sections_dir.glob("*.md")
                           if p.name not in excluded)

    records, pages, structure, expected = [], [], [], 0
    # The guides mark parts two ways: Forecasting uses a <!-- part: --> comment
    # in every section, ML-Stats uses a single "# Part A: ..." heading that
    # applies until the next one. Both carry forward to later sections.
    running_part = ""

    for section_file in section_files:
        raw = section_file.read_text(encoding="utf-8")
        expected += len(MD_QUESTION_LINE.findall(raw))
        clean = HTML_COMMENT.sub("", raw)

        part_match = PART_META.search(raw)
        h1 = HEADING_H1.search(clean)
        if part_match:
            running_part = part_match.group(1).strip()
        elif h1:
            running_part = h1.group(1).strip()
        part = running_part

        # The section's own name is its h2. Fall back to the h1, then the
        # filename, so a section is never left unlabelled.
        h2 = HEADING_H2.search(clean)
        if h2:
            section_title = h2.group(1).strip()
        elif h1:
            section_title = h1.group(1).strip()
        else:
            section_title = section_file.stem

        doc = run_pandoc(HTML_COMMENT.sub("", raw), section_file.name)
        level3 = [n for n in parse_sections(doc) if "level3" in n["cls"]]
        has_questions = any(re.match(r"^q\d", n["id"], re.IGNORECASE)
                            for n in level3)

        # Some sections carry no questions at all: the quick-revision sheets
        # and the end-to-end capstones. They are reference reading, so they
        # become a page rather than being dropped.
        if not has_questions:
            page_id = guide["key"] + "-page-" + section_file.stem
            page_html, figures = rewrite_figures(
                doc, section_file, guide_root, guide["key"], figures_out,
                page_id, problems)
            page = {
                "id": page_id,
                "guide": guide["key"],
                "part": part,
                "section": section_file.stem,
                "section_title": section_title,
                "html": style_zones(page_html),
                "figures": figures,
                "words": len(strip_tags(page_html).split()),
            }
            pages.append(page)
            structure.append({
                "section": section_file.stem,
                "section_title": section_title,
                "part": part,
                "kind": "page",
                "ids": [page_id],
            })
            continue

        current = None
        in_section = []

        for node in level3:
            if not re.match(r"^q\d", node["id"], re.IGNORECASE):
                # A subsection inside a long answer. Keep it with its question.
                if current is None:
                    problems.append(
                        section_file.name + ": a heading before the first "
                        "question was dropped (id=" + repr(node["id"]) + ")")
                else:
                    current["answer_html"] += node["inner"]
                continue

            heading_match = FIRST_H3.search(node["inner"])
            if not heading_match:
                raise BuildError(section_file.name + ": section "
                                 + repr(node["id"]) + " has no h3 heading")

            question_html = heading_match.group(1).strip()
            answer_html = node["inner"].replace(heading_match.group(0), "", 1)

            number_match = QNUM.match(strip_tags(question_html))
            if not number_match:
                raise BuildError(section_file.name + ": cannot read a question "
                                 "number from " + repr(question_html[:80]))
            qnum = number_match.group(1)

            # Keep the heading's own markup (italics etc.) minus the number.
            display_html = re.sub(r"^\s*" + re.escape(qnum) + r"[.:\s]\s*", "",
                                  question_html, count=1)

            current = {
                "id": guide["key"] + "-" + qnum,
                "guide": guide["key"],
                "part": part,
                "section": section_file.stem,
                "section_title": section_title,
                "qnum": qnum,
                "question_html": display_html,
                "question_text": " ".join(strip_tags(display_html).split()),
                "answer_html": answer_html,
                "figures": [],
            }
            records.append(current)
            in_section.append(current["id"])

        structure.append({
            "section": section_file.stem,
            "section_title": section_title,
            "part": part,
            "kind": "questions",
            "ids": in_section,
        })

    # Figures: resolve, copy, rewrite the src to the app-relative path.
    for record in records:
        section_file = sections_dir / (record["section"] + ".md")
        record["answer_html"], record["figures"] = rewrite_figures(
            record["answer_html"], section_file, guide_root, guide["key"],
            figures_out, record["id"], problems)
        record["answer_html"] = style_zones(record["answer_html"])
        words = len(strip_tags(record["answer_html"]).split())
        record["words"] = words
        record["is_long"] = words > LONG_ANSWER_WORDS

    return records, pages, structure, expected


def check_sources_are_read_only():
    """The guides are facts. Refuse to run if we could write into them.

    Every write in this script goes under OUT_ROOT. If OUT_ROOT ever sat
    inside SOURCE_ROOT, a build could overwrite source material, so that
    arrangement is rejected outright rather than trusted to stay safe.
    """
    source = SOURCE_ROOT.resolve()
    out = OUT_ROOT.resolve()
    if out == source or source in out.parents or out in source.parents:
        raise BuildError(
            "refusing to build: the output folder\n    " + str(out)
            + "\nand the source guides\n    " + str(source)
            + "\nmust be separate folders, so a build can never write over "
              "your documents.")


def main():
    if shutil.which("pandoc") is None:
        raise BuildError("pandoc is not on PATH. Install pandoc and retry.")

    check_sources_are_read_only()

    data_out = OUT_ROOT / "data"
    figures_out = OUT_ROOT / "figures"
    data_out.mkdir(exist_ok=True)

    problems = []
    index = {"guides": [], "questions": {}, "pages": {}}
    all_ids = []
    total_records = total_pages = total_expected = 0

    for guide in GUIDES:
        print("  " + guide["title"] + " ...", end="", flush=True)
        records, pages, structure, expected = build_guide(
            guide, figures_out, problems)
        total_records += len(records)
        total_pages += len(pages)
        total_expected += expected
        print(" " + str(len(records)) + " questions (source says "
              + str(expected) + "), " + str(len(pages)) + " reference pages")

        if len(records) != expected:
            problems.append(guide["key"] + ": built " + str(len(records))
                            + " questions but the source files contain "
                            + str(expected))

        # Questions and pages share one shape so the app fetches them alike.
        content = {}
        empty = []
        for r in records:
            all_ids.append(r["id"])
            content[r["id"]] = {"answer_html": r["answer_html"],
                                "figures": r["figures"]}
            if not strip_tags(r["answer_html"]).strip():
                empty.append(r["id"])
        for p in pages:
            all_ids.append(p["id"])
            content[p["id"]] = {"answer_html": p["html"],
                                "figures": p["figures"]}
            if not strip_tags(p["html"]).strip():
                empty.append(p["id"])
        if empty:
            problems.append(guide["key"] + ": empty content: " + str(empty[:10]))

        (data_out / (guide["key"] + ".json")).write_text(
            json.dumps(content, ensure_ascii=False), encoding="utf-8")

        index["guides"].append({
            "key": guide["key"],
            "title": guide["title"],
            "blurb": guide["blurb"],
            "count": len(records),
            "pages": len(pages),
            "sections": structure,
        })
        for r in records:
            index["questions"][r["id"]] = {
                "id": r["id"], "guide": r["guide"], "qnum": r["qnum"],
                "part": r["part"], "section": r["section"],
                "section_title": r["section_title"],
                "question_html": r["question_html"],
                "question_text": r["question_text"],
                "words": r["words"], "is_long": r["is_long"],
                "has_figure": bool(r["figures"]),
            }
        for p in pages:
            index["pages"][p["id"]] = {
                "id": p["id"], "guide": p["guide"], "part": p["part"],
                "section": p["section"], "section_title": p["section_title"],
                "words": p["words"], "has_figure": bool(p["figures"]),
            }

    # --- checks: fail loudly rather than ship a quietly wrong app ----------
    # Checked against the list, not the dict: dict keys dedupe silently.
    seen, duplicates = set(), set()
    for qid in all_ids:
        if qid in seen:
            duplicates.add(qid)
        seen.add(qid)
    if duplicates:
        problems.append("duplicate question ids: " + str(sorted(duplicates)[:10]))

    figure_count = len(list(figures_out.rglob("*.png"))) if figures_out.is_dir() else 0
    index["totals"] = {"questions": total_records, "pages": total_pages,
                       "figures": figure_count}
    (data_out / "index.json").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8")

    print("\n  total: " + str(total_records) + " questions, "
          + str(total_pages) + " reference pages, "
          + str(figure_count) + " figures")

    if problems:
        print("\nBUILD FAILED:\n")
        for p in problems:
            print("  - " + p)
        return 1

    print("  all checks passed")

    # A build only ever writes data/ and figures/. Say so out loud, with
    # counts, so it is obvious nothing of yours was touched.
    notes = list((OUT_ROOT / "notes").glob("*.md")) if (OUT_ROOT / "notes").is_dir() else []
    # An audio sibling is not a take of its own; counting them would double
    # every number printed here.
    takes = ([f for f in (OUT_ROOT / "recordings").glob("*.webm")
              if not f.name.endswith(".audio.webm")]
             if (OUT_ROOT / "recordings").is_dir() else [])
    state = OUT_ROOT / "state.json"
    marks = 0
    if state.is_file():
        try:
            marks = len(json.loads(state.read_text(encoding="utf-8")).get("marks", {}))
        except (ValueError, OSError):
            marks = 0
    print("\n  Your own work, untouched by this build:")
    print("    notes        " + str(len(notes)))
    print("    recordings   " + str(len(takes)) + " ("
          + str(round(sum(f.stat().st_size for f in takes) / 1048576, 1)) + " MB)")
    print("    marked       " + str(marks))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BuildError as exc:
        print("\nBUILD FAILED: " + str(exc))
        sys.exit(1)
