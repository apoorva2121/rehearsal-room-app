#!/usr/bin/env python3
"""Does the grader actually grade, or does it just flatter you?

Three answers to the same question are sent through it: one good, one with a
known gap, one confidently wrong. The third is the one that matters -- a
grader that passes a confident wrong answer is worse than no grader, because
it tells you you are ready when you are not.

Run:  python test_grading.py        (needs a key; costs a few cents)
"""
import sys

import ai

QUESTION = "ml-stats-Q1.1"   # supervised vs unsupervised vs semi-supervised

# Written the way they come out of speech-to-text: no punctuation, no
# capitals, jargon slightly mangled. The grader must cope with that.
GOOD = (
    "so supervised learning is where you have inputs and known labels and you "
    "learn a mapping to predict the label on new inputs spam detection house "
    "prices that kind of thing unsupervised you only have the inputs no "
    "labels and you are looking for structure clusters segments anomalies and "
    "semi supervised sits between them you have a small labelled set and a "
    "much larger unlabelled set and you are trying to get supervised level "
    "accuracy without paying for all the labels the usual method is pseudo "
    "labelling where the model labels the unlabelled data itself and learns "
    "from its own confident guesses but the important caveat is that only "
    "works if the unlabelled data comes from the same distribution as the "
    "labelled data if it does not you can actually do worse because early "
    "wrong guesses reinforce themselves and the other thing i would say is "
    "with unsupervised there is no ground truth so you judge it by whether it "
    "is useful downstream not by a score"
)

KNOWN_GAP = (
    "supervised learning uses labelled data so you have the answers and you "
    "train a model to predict them unsupervised has no labels at all so it "
    "finds patterns on its own and semi supervised is a mix of the two you "
    "use some labelled data and some unlabelled data together that is "
    "basically the difference between them"
)
# What it never says: what makes semi-supervised work at all (the unlabelled
# data has to come from the same distribution), and that it can hurt.

CONFIDENTLY_WRONG = (
    "right so supervised learning is where all your labels are correct "
    "unsupervised is where you have no labels and semi supervised is the case "
    "where roughly half your labels are wrong or noisy so you are learning "
    "through the noise and honestly in practice unsupervised almost always "
    "beats supervised once you have enough data because the model is not "
    "constrained by human labels which are biased anyway so i would reach for "
    "clustering first on any large dataset and only label if clustering fails"
)

# Things a reader might not follow in this answer, and one that is nowhere
# near it -- the explainer must help with both and say which is which.
EXPLAIN_ASKS = [
    ("in the material", "pseudo-labelling"),
    ("outside it", "how to size a kubernetes horizontal pod autoscaler"),
]

fails = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label
          + ((" :: " + str(detail)) if detail else ""))
    if not ok:
        fails.append(label)


def show(grade):
    print("    verdict : %s -- %s" % (grade["verdict"], grade["verdict_note"]))
    for m in grade["missed"]:
        print("    missed  : " + m)
    for w in grade["wrong"]:
        print("    wrong   : %s -- %s" % (w.get("said"), w.get("why")))
    s = grade["scores"]
    print("    scores  : correctness %s, depth %s, articulation %s"
          % (s.get("correctness"), s.get("depth"), s.get("articulation")))
    print("    delivery: " + grade["delivery"])


def main():
    if not ai.find_key():
        print("No key, so nothing to test. Put one in %s first."
              % ai.key_location())
        return 1
    print("grading with %s\n" % ai.CHAT_MODEL)

    print("1. a good answer")
    good = ai.grade(QUESTION, GOOD)
    show(good)
    check("a good answer is not failed",
          good["verdict"] in ("WOULD PASS", "BORDERLINE"), good["verdict"])
    check("a good answer scores 4+ on correctness",
          (good["scores"].get("correctness") or 0) >= 4,
          good["scores"].get("correctness"))
    check("a good answer is not accused of being wrong",
          not good["wrong"], good["wrong"])

    print("\n2. an answer with a known gap")
    gap = ai.grade(QUESTION, KNOWN_GAP)
    show(gap)
    check("the gap is noticed at all", bool(gap["missed"]))
    missed = " ".join(gap["missed"]).lower()
    check("it names the distribution/assumption gap",
          any(word in missed for word in
              ("distribution", "assumption", "cluster", "same", "pseudo",
               "hurt", "harm")),
          gap["missed"])
    check("a thin answer does not score 5s",
          (gap["scores"].get("depth") or 5) <= 3, gap["scores"])

    print("\n3. a confidently wrong answer -- the one that matters")
    wrong = ai.grade(QUESTION, CONFIDENTLY_WRONG)
    show(wrong)
    check("a confidently wrong answer is NOT passed",
          wrong["verdict"] != "WOULD PASS", wrong["verdict"])
    check("it says plainly that something was wrong",
          bool(wrong["wrong"]), wrong["wrong"])
    check("confidence does not buy a correctness score above 2",
          (wrong["scores"].get("correctness") or 5) <= 2,
          wrong["scores"].get("correctness"))

    print("\n4. the concept explainer keeps to three lines")
    for where, question in EXPLAIN_ASKS:
        reply = ai.explain(QUESTION, question)
        lines = reply["text"].splitlines()
        print("    asked (%s): %s" % (where, question))
        for line in lines:
            print("      " + line)
        # Exactly three, not "three or fewer" -- a single run-on paragraph
        # satisfies "or fewer" while being precisely the thing to prevent.
        check("'%s' answered in exactly 3 lines" % where,
              len(lines) == 3, len(lines))
        check("'%s' last line is the tie-back" % where,
              bool(lines) and lines[-1].startswith("->"), lines[-1][:40])
        check("'%s' lines are short, not paragraphs" % where,
              all(len(l) <= 180 for l in lines),
              [len(l) for l in lines])
        if where == "outside it":
            check("a question outside the material is flagged as such",
                  "not in your material" in reply["text"].lower(),
                  lines[-1][:60])

    print("\n%d checks failed" % len(fails))
    for f in fails:
        print("  - " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ai.Problem as problem:
        print("\nstopped: [%s] %s" % (problem.kind, problem.message))
        sys.exit(1)
