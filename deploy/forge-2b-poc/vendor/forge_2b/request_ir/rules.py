"""Rule lexicon for DCE-G1 (English + Ukrainian). Pure ``re``; every pattern is matched on the original utterance.

Conventions
- Action triggers match only at the start of a clause (after bullets / politeness prefixes) or right after a
  connective. A verb in the middle of a clause ("the file lists all ports") is not a trigger — such clauses become
  context statements or unresolved nodes.
- ``ACTION_RULES`` is priority-ordered: the first family whose pattern matches wins. Multi-word, more specific forms
  precede generic ones (``say whether`` → assess before ``say which`` → identify before bare ``which``).
- Rule ids are ``<lang>.<family>.<action>``; the id is recorded on every emitted node for provenance.
"""
from __future__ import annotations

import re

I = re.I | re.U
W = r"(?<![\w'’-])"     # word start that also blocks hyphen/apostrophe-joined tokens
E = r"(?![\w'’-])"


def _w(alts: str) -> str:
    return rf"{W}(?:{alts}){E}"


# --- prefixes stripped before trigger matching (never part of the target) ------------------------------------------
BULLET_RE = re.compile(r"^\s*(?:[-*•–—]|\(?\d{1,2}[.)]|[a-z][.)]|\(?[ivx]{1,4}\))\s+", I)
LABEL_RE = re.compile(r"^\s*[^\s:]{1,24}(?: [^\s:]{1,24}){0,2}:\s+(?=\S)")   # "Ports: list them"  (≤3-word label)
PREFIX_RES = [re.compile(p, I) for p in (
    r"^\s*(?:please|pls|kindly|also|now|just|additionally|first of all|basically|simply|quickly|briefly|and|then|so|immediately|right away|at once|straight away|"
    r"просто|будь ласка|також|одразу|негайно|відразу)[,\s]+",
    r"^\s*(?:hypothetically|in theory|theoretically|for the sake of argument|гіпотетично|теоретично|instead|натомість|замість цього)[,\s]+",
    r"^\s*(?:answer|reply|respond|відповідай(?:те)?|відповідь|відповісти)\s+(?=(?:in|into|as|у|в|як|українською|англійською)\b)",   # "Answer in Ukrainian" → the locale is the content
    r"^\s*(?:could|can|would|will|might) you(?: please)?(?: also)?(?: just)?\s+(?!(?:not|never|ever)\b)",
    # permission grants are requests, not conditions: "but you may suggest better names" / "feel free to propose …"
    # (never when a negation follows: "you may not change …" / "you can not …" are prohibitions)
    r"^\s*(?:you (?:may|can|could|might|should|are welcome to|'re welcome to)(?: also| still| of course)?|feel free to|it'?s (?:ok|okay|fine) to|"
    r"можеш|можете|можна|не соромся|не соромтеся|за бажанням)\s+(?!(?:not|never|ever)\b)",
    r"^\s*(?:i|we)(?: would| 'd|'d| also)? (?:want|need|would like|like|expect|ask|require)(?: you)?(?: to)?\s+(?!(?:not|never)\b)",
    r"^\s*(?:you (?:should|must|need to|have to|can|could|may))\s+(?!(?:not|never|ever)\b)",
    r"^\s*(?:do you (?:know|think|see|have an idea))\s+(?:of |about )?",
    r"^\s*(?:i'?m looking for|i am looking for|i'?d appreciate)\s+",
    r"^\s*(?:будь ласка|будь-ласка|прошу|також|ще|і|та|й|а також|а ще)[,\s]+",
    r"^\s*(?:чи (?:можеш|можете|могли б ви|можна|не міг би ти|не могли б ви))(?: будь ласка)?\s+",
    r"^\s*(?:мені потрібно|мені треба|я хочу|я б хотів|я б хотіла|нам потрібно|нам треба|треба|потрібно|необхідно)(?:,? щоб ти| щоб ви)?\s+",
    r"^\s*(?:ти (?:повинен|маєш|можеш)|ви (?:повинні|маєте|можете))\s+",
)]

# --- temporal subordinators at clause start (explicit ordering) ----------------------------------------------------
# "after listing the ports, compare them" → following clause depends on this one; "before comparing, list" → this
# clause depends on the following one. Only these words; "first" alone creates no link.
SUBORD_AFTER_RE = re.compile(rf"^\s*(?:(?:after|once|when|having|as soon as)|(?:після того,? як|після того як|коли|щойно|як тільки))\s+", I)
SUBORD_BEFORE_RE = re.compile(rf"^\s*(?:before|перш ніж|перед тим,? як|перед тим як|до того,? як)\s+", I)
GERUND_RE = re.compile(r"^\s*([a-z]+ing)\b", I)

# --- conditions (v0.1): explicit subordinate qualifiers → Condition nodes, never objectives -------------------------
# kind by marker; "when/once" are temporal (after), "if/provided/in case" are conditional.
CONDITION_MARKERS: list[tuple[str, str]] = [
    ("unless", r"unless|якщо не|хіба що"),
    ("until", r"until|till|поки не|доки не|допоки не"),
    ("if", r"even if|what if|if|provided that|provided|in case|as long as|assuming(?: that)?|supposing(?: that)?|suppose(?: that)?|imagine(?: that)?|"
            r"навіть якщо|а якщо|якщо|якби|за умови,? що|у разі,? якщо|у випадку,? якщо|припустімо,? що|припустимо,? що|уявімо,? що|уяви,? що|припустімо|припустимо|уявімо"),
    ("after", r"after|once|when|as soon as|having|після того,? як|коли|щойно|як тільки"),
    ("before", r"before|prior to|ahead of|перш ніж|перед тим,? як|до того,? як"),
    # "whenever a test references X, flag it" quantifies over the tests (the pronoun names the iterated item) → for_each
    # "for each <noun>, …" opens a loop; a bare "for each" at the end of a clause is anaphoric ("a plan for each") and stays in the object
    ("for_each", r"for (?:each|every)(?=\s+[^\W\d_])|whenever|each time|every time|for (?:those|these|each of (?:them|those|these))(?=\s*(?:,|$))|"
                 r"для кожного|для кожної|для кожних|щоразу,? коли|кожного разу,? коли"),
]
_COND_ALTS = "|".join(p for _, p in CONDITION_MARKERS)
CONDITION_START_RE = re.compile(rf"^\s*(?:{_COND_ALTS})\b[,\s]*", I)
TRAILING_CONDITION_RE = re.compile(rf"(?:,\s*|\s+)(?:{_COND_ALTS})\b", I)
ELSE_START_RE = re.compile(r"^\s*(?:otherwise|or else|else|if not|інакше|в іншому випадку|у протилежному випадку|якщо ні)[,:\s]+", I)
# temporal markers only open a clause when a clause follows (gerund, pronoun subject, or "the X is/fails/…");
# "works after the patch" is a prepositional phrase, not a condition
CLAUSE_AFTER_MARKER_RE = re.compile(
    r"^\s*(?:[a-z]+ing\b|[а-яіїєґ’']+(?:ти|тись|ться)\b|(?:you|we|i|they|it|he|she|one|я|ти|ви|ми|вони|він|вона|воно)\b|(?:that|this|the|a|an|my|our|your|all|any|every|each|no|"
    r"цей|ця|це|ці|той|та|те|ті|всі|усі|кожен|кожна|жоден)\b(?:\s+\S+){0,5}?\s+(?:is|are|was|were|has|have|had|does|do|did|will|would|can|could|should|"
    r"fails?|failed|finish(?:es|ed)?|pass(?:es|ed)?|complete[sd]?|ends?|ended|runs?|ran|starts?|started|exists?|returns?|returned|breaks?|broke|"
    r"references?|mentions?|uses?|calls?|imports?|depends|contains?|includes?|matches|changes?|changed|touches|reports?|logs?|throws?|times out|hits?|exceeds?|"
    r"drops?|reaches|crosses|appears?|shows?|points?|refers?|needs?|requires?|lacks?|misses|fires?|triggers?|emits?|produces?|outputs?|receives?|gets?|sends?|"
    r"detects?|finds?|encounters?|sees?|reads?|writes?|opens?|closes?|connects?|expires?|restarts?|crashes|hangs?|stalls?|succeeds?|goes|comes|becomes?|"
    r"посилається|згадує|використовує|містить|включає|змінюється|падає|перевищує|з'являється|потребує|вимагає|надсилає|отримує|виявляє|знаходить|відкриває|закриває|"
    r"є|буде|будуть|був|була|було|були|має|мають|падають|падає|впав|впали|завершиться|завершено|готовий|готова|готово|готові)\b|"
    r"(?:needed|necessary|possible|applicable|required|relevant|потрібно|необхідно|можливо|треба)\b|"
    # "перш ніж щось виконувати" / "before anything is executed" — an indefinite object + infinitive/passive still opens a clause
    r"(?:щось|що-небудь|будь-що|нічого|anything|something|everything)\s+(?:[а-яіїєґ’']+(?:ти|тись|ться)|is|gets|has been|was)\b)", I)
# pronoun/aux subject stripped before looking up the verb a condition merely *mentions*
COND_SUBJECT_RE = re.compile(r"^\s*(?:(?:you|we|i|they|it|he|she|я|ти|ви|ми|вони|він|вона|воно)\s+)?"
                             r"(?:(?:will|would|can|could|should|must|may|might|do|does|did|have to|need to|are|is|am|were to|are to|was to|"
                             r"would like to|want to|plan to|intend to|decide to|try to|(?:am|are|is) going to|happen to|хочу|хочеш|плануєш|плануємо|збираюся|збираєшся)\s+)?", I)
# finite / participle forms of the verbs whose *mention* matters for authorization (never triggers)
MENTION_FORMS: list[tuple[str, re.Pattern[str]]] = [
    ("run", re.compile(_w(r"запустив|запустила|запустили|виконав|виконала|виконали|розгорнув|розгорнула|перезапустив|перезапустила|встановив|встановила|running|executing|launching|starting|restarting|deploying|installing|applying|calling|invoking|publishing|sending|uploading|submitting|triggering|"
                          r"connecting|sshing|logging in|signing in|pinging|curling|"
                          r"runs|executes|deploys|applies|publishes|sends|sent|submits|triggers|connects|"
                          r"запущу|запустиш|запустить|запустимо|запустите|запустять|запускаючи|запускати|запустити|виконувати|виконати|"
                          r"виконуючи|виконаю|виконаєш|виконає|виконаємо|виконаєте|виконають|розгортаючи|розгортати|застосовуючи|застосувати|"
                          r"перезапускати|перезапускаючи|перезапустити|надсилаючи|надсилати|надіслати|відправляти|відправити|встановлюючи|встановлювати|встановити"), I)),
    ("remove", re.compile(_w(r"видалив|видалила|видалили|знищив|знищила|стер|стерла|дропнув|deleting|removing|dropping|erasing|purging|wiping|deletes|removes|видалю|видалиш|видалить|видалимо|видалите|видалять|видаляючи|"
                             r"видаляти|видалити|вилучаючи|вилучати|вилучити|очищаючи|очистити"), I)),
    ("modify", re.compile(_w(r"змінив|змінила|змінили|відредагував|оновив|оновила|виправив|виправила|editing|modifying|changing|updating|fixing|patching|renaming|replacing|configuring|changes|modifies|edits|updates|"
                             r"зміню|зміниш|змінить|змінимо|зміните|змінять|змінюючи|змінювати|змінити|редагуючи|редагувати|модифікуючи|оновлюючи|оновити|"
                             r"виправляючи|виправити|налаштовуючи"), I)),
    ("create", re.compile(_w(r"створив|створила|створили|додав|додала|написав|написала|creating|writing|generating|adding|implementing|creates|створюючи|створювати|створити|створю|створиш|створить|додаючи|додати|пишучи"), I)),
    ("recommend", re.compile(_w(r"recommending|suggesting|proposing|advising|пропонуючи|пропонувати|рекомендуючи|рекомендувати|радячи|радити|порадити"), I)),
    ("verify", re.compile(_w(r"verifying|validating|confirming|checking|testing|перевіряючи|перевіряти|перевірити|перевірю|перевіриш|перевірите|перевіримо|підтверджуючи|підтвердити"), I)),
    ("show", re.compile(_w(r"opening|viewing|displaying|showing|відкриваючи|переглядаючи"), I)),
    ("compare", re.compile(_w(r"comparing|порівнюючи"), I)),
    ("enumerate", re.compile(_w(r"listing|перелічуючи"), I)),
    ("summarize", re.compile(_w(r"summari[sz]ing|підсумовуючи"), I)),
    ("extract", re.compile(_w(r"extracting|printing|quoting|витягуючи|друкуючи"), I)),
    ("analyze", re.compile(_w(r"analy[sz]ing|аналізуючи"), I)),
    ("inspect", re.compile(_w(r"reviewing|inspecting|examining|reading|переглядаючи|читаючи"), I)),
    ("translate", re.compile(_w(r"translating|перекладаючи"), I)),
]
UK_PARTICIPLE_RE = re.compile(r"^\s*\S+(?:ючи|ачи|вши|ючись|ачись)\b", I)
# objects that make a prohibition global rather than a specific action+object pair
GENERIC_OBJECT_RE = re.compile(
    r"^\s*(?:anything(?: at all| else)?(?: (?:in|on|at|inside|under|within|у|в|на) \S+)?|everything|something|any(?:thing)? (?:file|files|code|change|changes|thing|things)|"
    r"(?:any|all|every|either of|any of|all of|none of) \S.*?|(?:the |any |all )?files|(?:the |any )?code|"
    r"(?:a |any |the )?changes?|nothing|all of it|будь-що|нічого|все|усе|(?:всі |усі |жодних |жодні )?файл(?:и|ів)|(?:жодного )?файлу|код|зміни|змін|жодних змін)"
    r"(?:\s+(?:yet|now|for now|at this point|at all|поки що|зараз))?\s*[.!…]*\s*$", I)
# "or" between two imperative heads → alternative objectives
ALTERNATIVE_RE = re.compile(rf"(?:,\s*)?\s+{W}(?:or|or else|або|чи)\b(?:,\s*|\s+)", I)

# --- sequence markers (clause split + depends_on link to the most recent earlier objective) -------------------------
SEQUENCE_RE = re.compile(
    rf"(?:,|;|\s)\s*(?:(?:and|та|і|й)\s+)?{W}(?:and then|(?<!until )(?<!till )(?<!by )then|after that|after this|afterwards|afterward|next|finally|lastly|subsequently|once (?:that is|that's|you have|you've) done|when (?:that is|you are) done|"
    rf"а потім|потім|після цього|після того(?!,?\s+як\b)|далі|наостанок|нарешті|насамкінець|згодом|відтак|і тоді|тоді)\b[,:]?\s*", I)
SEQUENCE_START_RE = re.compile(
    rf"^\s*(?:and then|then|after that|after this|afterwards|afterward|next|finally|lastly|subsequently|"
    rf"а потім|потім|після цього|після того(?!,?\s+як\b)|далі|наостанок|нарешті|насамкінець|згодом|відтак|і тоді|тоді)\b[,:]?\s+", I)
# "first/спочатку" only strips; ordering is created by the later "then"
INSTEAD_RE = re.compile(r"^\s*(?:instead|натомість|замість цього|in the meantime|in the interim|meanwhile|тим часом|а тим часом|for now|поки що|а поки що|а поки|наразі)[,:]?\s+", I)
# a clause opened by one of these is delivered *now*: a sentence-initial condition ("After my approval, change X — meanwhile describe Y") does not govern it
MEANWHILE_RE = re.compile(r"\s*(?:in the meantime|in the interim|meanwhile|for now|тим часом|а тим часом|поки що|а поки що|а поки(?! не)|поки(?! не)|наразі)[,:]?\s+", I)
# "After my approval, change the config" / "Після мого підтвердження зміни конфігурацію" / "Once approved, …" — a noun-phrase approval condition ahead of the request
APPROVAL_NP_CONDITION_RE = re.compile(
    r"^\s*(?:(?P<after>after|upon|following|once|після|по|після того як отримаю)\s+(?:my |your |our |the |team |manager's |lead's |explicit |written |final |мого |вашого |твого |нашого |моєї |вашої |вашої )*"
    r"(?:approval|confirmation|sign[- ]?off|go[- ]?ahead|green light|authori[sz]ation|ok|okay|consent|review|підтвердження|схвалення|погодження|дозволу|узгодження|апруву|перевірки)"
    r"(?:\s+(?:from|by|від)\s+[\w'’-]+(?:\s+[\w'’-]+)?)?|(?P<after2>once|when|after|після того,? як|коли|щойно)\s+(?:it is |this is |that is |це |ми |я )?(?:approved|confirmed|signed off|cleared|authori[sz]ed|green-?lit|схвалено|підтверджено|погоджено|дозволено|схвалю|підтверджу|погоджу))"
    r"(?=[,:—–-]|\s)[,:—–-]?\s*", I)
# "Not until sign-off should you delete stale branches" — a deferred prohibition: forbidden now, conditioned on the until-clause
NOT_UNTIL_RE = re.compile(r"^\s*not (?P<kind>until|before|unless) (?P<cond>.+?)\s+(?:should|may|can|must|are|do|will|shall|would)\s+you\s+(?P<rest>.+)$", I)
# "No touching live cluster settings" / "No deleting anything" — a gerund after a bare "No" is a prohibition of that action
NO_GERUND_RE = re.compile(r"^\s*no\s+(?P<ger>[a-z]+ing)\b\s*(?P<obj>.*)$", I)
# "Give two separate outputs: a risk table and an action checklist" — enumerated deliverables after a colon/dash
DELIVERABLES_RE = re.compile(r"^\s*(?:please\s+)?(?:give|provide|produce|prepare|return|output|deliver|make|дай|дайте|надай|надайте|підготуй|підготуйте|сформуй|сформуйте|зроби|зробіть)(?: me| us| мені| нам)?\s+"
                             r"(?:(?:two|three|four|five|\d+|the following|these|both|два|три|чотири|дві|наступні|такі|обидва)\s+)?(?:separate\s+|distinct\s+|окремі\s+|окремих\s+)?"
                             r"(?:outputs?|deliverables?|things|artefacts?|artifacts?|items|parts|sections|documents?|pieces|результати|результат[иу]|речі|частини|документи|артефакти|блоки)\s*[:—–-]\s*(?P<list>.+)$", I)
DELIVERABLE_SPLIT_RE = re.compile(r"\s*(?:,\s*(?:and|та|і|й)\s+|,\s*|;\s*|\s+(?:and|та|і|й)\s+(?=(?:a|an|the|one|some|окремий|окрему|окреме|ще)\b))", I)
FIRST_RE = re.compile(rf"^\s*(?:first(?:ly)?|to (?:start|begin)(?: with)?|start by|begin by|спочатку|спершу|перш за все|насамперед|по-перше)[,:]?\s+", I)

# --- coordination split: connective followed by an imperative/negation/exclusion/requirement start ----------------
COORD_RE = re.compile(rf"(?:,|;)?\s+{W}(?:and also|and|&|plus|as well as|also|but also|but|yet|та також|а також|також|та|і|й|але|проте|однак|а)\b(?:,\s*|\s+)", I)
FIRST_PERSON_CLAUSE_RE = re.compile(r"\s*(?:i|we)(?:'ll| will| am going to| are going to| can| could| would| shall|'d| myself| ourselves| just want| only want| want to know| need to know| am not| have not| haven't| pasted| attached| я| ми)\b|\s*(?:я|ми)\s+(?:сам|сама|самі|зроблю|зробимо|запущу|запустимо|буду|будемо)\b", I)
COMMA_RE = re.compile(r",\s+|\s+[—–]\s+")     # a spaced dash separates clauses like a comma ("…: rm -rf x — explain …")

# --- negation / prohibition at clause start --------------------------------------------------------------------
# deontic negatives with an explicit addressee/inclusive subject are prohibitions ("we must not delete the database",
# "you are not allowed to change …", "you should never run …"); a third-party subject ("the job should never run") stays a statement
DEONTIC_NEG = (r"(?:(?:we|you|one|ти|ви|ми|тобі|вам|нам|мені)\s+)?(?:must not|mustn'?t|should not|shouldn'?t|shall not|"
               r"it(?:'s| is) (?:forbidden|prohibited|not allowed|not permitted|not acceptable|not ok(?:ay)?|unacceptable) to|"
               r"(?:are|is) not (?:allowed|permitted|supposed|authori[sz]ed|expected) to|(?:are|is) forbidden to|(?:are|is) not to|"
               r"(?:should|must|may|shall) never|(?:are|is) never to|"
               r"не повинн[іа]|не повинен|не ма(?:єш|єте) права|не можна|не дозволено|не дозволяється|у жодному разі не|ні в якому разі не)|"
               r"(?:we|you|one|ти|ви|ми)\s+(?:cannot|can'?t|can not|may not|can never|не можеш|не можете)")
PROHIBITION_START_RE = re.compile(
    rf"^\s*(?:please\s+)?(?:(?:do not|don'?t|dont|never|avoid|refrain from|please refrain from|{DEONTIC_NEG}|no need to|stop|don't ever|do not ever|without|not|(?:i|we) (?:forbid|prohibit|do not allow|don'?t allow|will not allow|won'?t allow|do not permit|don'?t permit|do not authori[sz]e|don'?t authori[sz]e)|(?:я |ми )?заборон(?:яю|яємо))|"
    rf"(?:нічого не|нікого не|ніколи нічого не|не|ніколи не|не треба|не потрібно|не слід|без|жодних|заборонено|уникай|уникайте|утримайся від|утримайтеся від))"
    rf"(?:,?\s*(?:under any circumstances|under no circumstances|at any point|in any case|for any reason|за жодних обставин|ні за яких обставин),?)?"
    rf"(?:\s+(?:please|also|ever|actually|really|just|simply|будь ласка|також|справді|просто))?\s+", I)
# "Not a single file may be deleted" / "No table must be dropped": a passive modal after a fronted negation → prohibition of the participle's action
PASSIVE_PROHIBITION_RE = re.compile(r"^\s*(?:a single|any|one|the|all|жоден|жодна|жодне|жодного|жодної)?\s*[\w'’-]*(?:\s+[\w'’-]+){0,3}?\s+"
                                    r"(?:may|must|should|can|shall|will|is to|are to|gets|get|is|are|will be|would be|shall be|(?:не )?(?:може|можуть|має|мають|повинен|повинна|повинні))\s+(?:be\s+|бути\s+)?"
                                    r"(?P<part>[\w'’-]+(?:ed|en|run|put|cut|set|hit|split|built|sent|read|made|written|done|gone|"
                                    r"[а-яіїєґ]+(?:аний|ений|єний|ений|ано|ено|єно|ані|ені|єні|ана|ена|єна)))\b", I)
NEG_SUBJECT_RE = re.compile(r"^\s*(?:nothing|nobody|no one|none(?: of (?:the|these|those|them))?|нічого|ніщо|ніхто|жоден|жодна|жодне|жодного|жодної)\b", I)
PASSIVE_PARTICIPLES = {"deleted": "remove", "removed": "remove", "dropped": "remove", "erased": "remove", "wiped": "remove", "purged": "remove",
                       "modified": "modify", "changed": "modify", "edited": "modify", "touched": "modify", "renamed": "modify", "altered": "modify",
                       "executed": "run", "run": "run", "deployed": "run", "installed": "run", "sent": "run", "published": "run", "restarted": "run", "started": "run",
                       "created": "create", "written": "create", "added": "create", "saved": "create",
                       "видалено": "remove", "видалені": "remove", "видалений": "remove", "змінено": "modify", "змінені": "modify", "запущено": "run", "створено": "create"}
# "Screenshots are not needed." / "Creating tickets is not part of this task." → nominal prohibition of the subject
DECL_NEG_RE = re.compile(
    r"^\s*(?P<noun>(?!(?:it|this|that|there|here|which|what)\b)[\w'’-]+(?:\s+[\w'’-]+){0,4}?)\s+(?:is|are|'s|’s|є)\s+"
    r"(?:not (?:needed|necessary|required|wanted|expected|desired|part of (?:this|the) (?:task|scope|request|job))|unnecessary|unneeded|out of scope|off[- ]limits|forbidden|not an option|"
    r"не потрібн[іаео]|непотрібн[іаео]|зайв[іаео]|не входить у (?:задачу|завдання)|поза межами задачі|заборонен[іаео])\b", I)
# "I don't want a rewrite" / "we do not need screenshots" → nominal prohibition
DONT_WANT_RE = re.compile(r"^\s*(?:i|we)\s+(?:don'?t|do not|didn'?t)\s+(?:want|need|expect)\s+(?P<noun>(?:(?:a|an|any|the|some)\s+)?[\w'’-]+(?:\s+[\w'’-]+){0,4}?)\s*[.!…]*\s*$", I)
# "Is it safe to…", "Would it be possible to…" — expletive *it* is not a referent
EXPLETIVE_IT_RE = re.compile(r"^(?:it|It)\s+(?:(?:is|was|would be|will be|might be|could be|seems|'s|’s)\s+)?(?:safe|possible|ok|okay|fine|worth|necessary|advisable|risky|dangerous|better|best|feasible|wise|a good idea|a bad idea|enough|likely|unlikely|true|clear)\b")
NO_NOUN_RE = re.compile(rf"^\s*(?:no|без|жодних)\s+(?!(?:one|body|longer|matter|doubt|way|idea|problem|worries|thanks)\b)(\w[\w\s-]{{0,40}}?)(?:,?\s*(?:please|будь ласка))?\s*$", I)     # "No recommendations, please."
NO_NOUN_HEAD_RE = re.compile(r"no\s+(?!(?:one|body|longer|matter|doubt|way|idea|problem|worries|thanks)\b)\w", I)   # ", but no shell commands" opens a clause
# "whether or not" is not a negation
WHETHER_OR_NOT_RE = re.compile(r"\bwhether\s+or\s+not\b|\bчи\s+ні\b", I)
# "Recommend nothing." — an imperative whose object is a null quantifier is a prohibition of that action
NULL_OBJECT_RE = re.compile(r"^\s*(?:nothing(?: at all| else)?|none(?: of them)?|nobody|no one|nichts|нічого|нікого|жодного|жодних|жодної)"
                            r"(?:\s+(?:in|on|at|inside|under|within|to|with|for|about|against|у|в|на|всередині|до|з|із|над|для)\s+[^,;]{1,40}?)?(?:\s+(?:yet|now|for now|at this point|поки що|зараз))?\s*[.!…]*\s*$", I)
# "<verb> nothing" — a null-object clause opens a clause even when the verb is unknown ("Touch nothing in production")
NULL_OBJECT_CLAUSE_RE = re.compile(r"^\s*(?:just\s+|simply\s+|please\s+|просто\s+)?(?P<verb>[^\W\d_]+)\s+(?:nothing|нічого|нікого)\b", I)
# "Run no scripts" / "Delete no files" / "Execute zero commands" / "Touch not a single file" — a negative object complement
# turns the imperative into a prohibition of that action on that object (never an objective)
NEG_OBJECT_RE = re.compile(r"^\s*(?:no|zero|not a single|not one|not any|none of the|none of these|none of those|жодних|жодного|жодної|жодну|жоден|ніяких)\s+"
                           r"(?P<noun>[^,;.!?]+?)(?:,?\s*(?:please|будь ласка))?(?:,?\s*(?:none at all|not a single one|not one|whatsoever|at all|ever|взагалі|жодного|жодної|зовсім|ніяких))?\s*[.!…]*\s*$", I)
# "Do not do so/that/this/it" — the prohibition refers back to the operation last mentioned in the utterance
DO_SO_RE = re.compile(r"^\s*(?:(?:actually|really|ever|just)\s+)?(?:do|do any of|do any part of|робити|роби|робіть|зроби|зробіть|вчиняти)\s+(?:(?:actually|really)\s+)?(?:so|that|this|it|those|these|any of (?:that|this|it|those)|такого|так|це|цього|того|подібного)\b", I)
# hypothetical questions about a side-effecting operation: "Would you delete the cluster if I asked?" is a question, not a directive
HYPO_PREFIX_RE = re.compile(r"^\s*(?:(?:would|might|could|will) you(?: ever| really| actually| hypothetically| in theory| theoretically)?(?: be (?:willing|prepared|able|ready) to| agree to| consider)?|"
                            r"(?:чи\s+)?(?:ти|ви)\s+б|(?:чи\s+)?б\s+(?:ти|ви))\s+(?!please\b)", I)
HYPO_ADVERB_RE = re.compile(r"\b(?:ever|really|actually|hypothetically|in theory|theoretically|in principle)\b", I)
HYPO_CONDITION_RE = re.compile(r"^\s*(?:if|якби|якщо б|if ever|even if)\s+(?:i|we|someone|somebody|anyone|a user|the user|an operator|the operator|я|ми|хтось|користувач)?\s*"
                               r"(?:ever\s+|really\s+|simply\s+|just\s+)?(?:asked|ask|told|tell|said|say|wanted|want|insisted|requested|request|ordered|instructed|demanded|"
                               r"попросив|попросила|попрошу|сказав|сказала|скажу|наказав|захотів|захочу)\b(?:\s+(?:you|me|us)\s+to)?|^\s*(?:if|якщо|якби)\s+(?:asked|told|instructed|requested|ordered|prompted|instructed to)\b", I)
# nouns that name an operation class — a nominal prohibition on them binds to the action ("No shell commands" → run)
RESTRICTED_NOUN_ACTION = {
    "shell command": "run", "shell commands": "run", "command": "run", "commands": "run", "script": "run", "scripts": "run", "shell": "run", "shell access": "run",
    "network call": "run", "network calls": "run", "api call": "run", "api calls": "run", "http request": "run", "http requests": "run", "external call": "run",
    "external calls": "run", "outbound call": "run", "outbound calls": "run", "deploy": "run", "deploys": "run", "deployment": "run", "deployments": "run",
    "install": "run", "installs": "run", "installation": "run", "installations": "run", "restart": "run", "restarts": "run", "execution": "run", "executions": "run",
    "migration run": "run", "job": "run", "jobs": "run", "pipeline run": "run", "pipeline runs": "run", "connection": "run", "connections": "run", "ssh": "run",
    "change": "modify", "changes": "modify", "edit": "modify", "edits": "modify", "modification": "modify", "modifications": "modify", "code change": "modify",
    "code changes": "modify", "config change": "modify", "config changes": "modify", "write": "modify", "writes": "modify", "rewrite": "modify", "rewrites": "modify",
    "rename": "modify", "renames": "modify", "refactor": "modify", "refactors": "modify", "refactoring": "modify", "patch": "modify", "patches": "modify",
    "deletion": "remove", "deletions": "remove", "removal": "remove", "removals": "remove", "drop": "remove", "drops": "remove", "purge": "remove", "cleanup": "remove",
    "file creation": "create", "new file": "create", "new files": "create", "new branch": "create", "new branches": "create",
    "deployment today": "run",
    "команд": "run", "команди": "run", "скриптів": "run", "скрипти": "run", "запусків": "run", "запуски": "run", "деплоїв": "run", "деплої": "run", "розгортань": "run",
    "змін": "modify", "зміни": "modify", "правок": "modify", "правки": "modify", "редагувань": "modify", "видалень": "remove", "видалення": "remove", "нових файлів": "create",
}
# an artefact that lives only in the reply: "set RUN_MODE=dry-run in an example response", "write it in your answer" → compose, never mutate
REPLY_ARTEFACT_RE = re.compile(r"\b(?:in|into|within|inside|as part of|as|у|в|до)\s+(?:an?\s+|the\s+|your\s+|my\s+|this\s+)?(?:(?:example|sample|illustrative|mock|hypothetical|draft|suggested|proposed|possible)\s+)?"
                               r"(?:response|reply|answer|output|chat|message|comment|example|snippet|прикладі|відповіді|відповідь|повідомленні)\b", I)
# "write READY" / "напиши 'OK'" / "write DONE in the reply" — a literal token to be written in the answer
LITERAL_TOKEN_RE = re.compile(r"^\s*(?:[\"'“«‘][^\"'”»’]{1,40}[\"'”»’]|(?-i:[A-Z][A-Z0-9_-]{1,30}))(?:\s+(?:in|to|as|у|в|до)\s+(?:the\s+|your\s+|my\s+)?"
                              r"(?:reply|response|answer|output|chat|message|відповіді|відповідь|повідомленні))?"
                              r"(?:\s*[.!…;,]*\s*$|\s*,?\s+(?:when|once|if|after|as soon as|at the end|at the (?:top|bottom|start)|on (?:success|failure|completion)|коли|якщо|після|щойно|наприкінці|в кінці|на початку)\b)", I)
# artefact nouns (shared by compose, nominal requests and deliverable coordination)
ARTEFACT_NOUNS = (r"table|list|summary|report|diagram|chart|example|examples|outline|plan|checklist|matrix|snippet|note|notes|doc|documentation|overview|comparison|"
                  r"timeline|runbook|release notes?|changelog|draft|proposal|brief|write-?up|readme|guide|tutorial|faq|glossary|body|payload|template|mock|sample|sketch|"
                  r"description|message|announcement|email|reply|response|answer|paragraph|title|caption|abstract|explanation|statement|spec|specification|rfc|adr|agenda|prompt|query|regex|"
                  r"breakdown|assessment|estimate|recap|tl;?dr|"
                  r"опис|повідомлення|відповідь|заголовок|пояснення|специфікацію|запит|анонс|лист|"
                  r"таблицю|таблиця|список|звіт|приклад|приклади|план|схему|схема|нотатку|чеклист|огляд|конспект|інструкцію|документацію|порівняння|перелік|підсумок|резюме")
# "…, then a detailed remediation plan" — a sequence marker followed by a deliverable noun phrase opens a nominal clause
SEQ_NOMINAL_RE = re.compile(rf"\s*(?:(?:a|an|the|another|one more|a second|some|окремий|окрему|окреме|ще один|ще одну|ще одне)\s+)?(?:[\w'’-]+\s+){{0,3}}?(?:{ARTEFACT_NOUNS})\b", I)
# "a table of endpoints and, separately, a list of risks" — two deliverables coordinated inside one object
COORD_ARTEFACT_RE = re.compile(rf"^(?P<first>.+?)(?P<sep>\s+(?:and|та|і|й|plus|as well as)(?:,\s*(?:separately|additionally|also|in addition|afterwards|окремо|також|додатково),?)?\s+)"
                               rf"(?P<second>(?:a|an|another|one more|a second|a separate|the|some|окремий|окрему|окреме|ще один|ще одну|ще одне)\s+(?:[\w'’-]+\s+){{0,3}}?(?:{ARTEFACT_NOUNS})\b.*)$", I | re.S)

# --- requirement / exclusion verbs at clause start (constraints on the previous objective) -----------------------
REQUIREMENT_START_RE = re.compile(
    rf"^\s*(?:please\s+)?(?:(?:also\s+)?include|including|make sure|ensure|always|be sure|remember to|cite|use|keep|be|stay|prefer|limit|restrict|focus on|stick to|mention|note|"
    rf"обов'язково|обов’язково|завжди|переконайся|переконайтеся|включи|включіть|додай посилання|зазнач|зазначте|вкажи джерела|будь|залишайся|використовуй|використовуйте|обмежся|зосередься)\b\s*", I)
EXCLUSION_START_RE = re.compile(
    rf"^\s*(?:please\s+)?(?:skip|omit|leave out|exclude|ignore|disregard|drop|except|excluding|rather than|instead of|пропусти|пропустіть|опусти|виключи|виключіть|ігноруй|ігноруйте|не враховуй|крім|окрім|замість того,? щоб|замість)\b\s*", I)

# --- inline constraints (inside an objective clause; each spans to the next marker or clause end) ------------------
INLINE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("exclusion", re.compile(_w(r"except(?: for)?|excluding|other than|apart from|but not|not including|without|minus|leaving out|omitting|ignoring|skipping|disregarding|rather than|instead of|"
                               r"крім|окрім|за винятком|без|але не|не враховуючи|виключаючи|окрім як|замість|а не"), I)),
    ("scope_only", re.compile(_w(r"only|solely|exclusively|nothing else|and nothing else|and nothing more|лише|тільки|виключно|і нічого більше|більше нічого"), I)),
    ("format", re.compile(_w(r"(?:as|in|into) (?:a |an |the |one |a single )?(?:short |brief |simple |single |numbered |bulleted |compact |plain )?(?:table|json|yaml|csv|markdown|md|bullet(?:ed)? (?:list|points)|bullets|numbered list|list|one line|a single line|"
                           r"one sentence|a sentence|plain text|html|code block|diagram|tabular form|paragraph)|in (?:tabular|json|yaml|csv|markdown) format|"
                           r"in (?:\d+|one|two|three|four|five) (?:words|sentences|lines|paragraphs|bullets)|"
                           r"(?:у вигляді|у форматі|в форматі|як) (?:таблиці|таблицю|json|yaml|csv|markdown|списку|список|маркованого списку|одного речення|абзацу|коду)|"
                           r"одним реченням|одним рядком|одним абзацом|у (?:\d+|одному|двох|трьох) (?:реченнях|рядках|абзацах)"), I)),
    ("locale", re.compile(_w(r"(?:in|into) (?:english|ukrainian|german|french|spanish|polish|russian|japanese|chinese|italian|portuguese)|"
                           r"(?:українською|англійською|німецькою|французькою|польською|російською|іспанською|італійською)(?: мовою)?"), I)),
    ("cardinality", re.compile(_w(r"(?:(?:in|within|у|в) )?(?:top|first|last|at most|at least|no more than|not more than|up to|under|fewer than|less than|maximum of|a maximum of|max|exactly) "
                                r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|thirty|fifty|a hundred|a few|several|a dozen)|"
                                r"(?:не більше|не менше|щонайбільше|щонайменше|максимум|мінімум|перші|топ|останні|рівно|до|принаймні) "
                                r"(?:\d+|одного|один|одну|два|двох|дві|три|трьох|чотири|чотирьох|п'ять|п’ять|п'яти|п’яти|десять|десяти|п'ятнадцяти|п’ятнадцяти|двадцять|двадцяти|тридцяти|сто|ста|кількох)")
                              + r"(?:\s+" + _w(r"items?|lines?|rows?|entries|entry|bullets?|bullet points?|words?|sentences?|results?|examples?|points?|files?|steps?|paragraphs?|findings?|issues?|"
                                              r"рядків|рядки|пунктів|пункти|елементів|слів|речень|прикладів|результатів|кроків|файлів|знахідок")
                              # quantifier domain: "no more than three bullets per finding" / "two examples for each service"
                              + r"(?:\s+(?:per|for each|for every|apiece|each|на кожн\w+|на|для кожн\w+)(?:\s+[^\W\d_][\w'’-]*){0,2})?)?", I)),
    ("ordering", re.compile(_w(r"(?:sorted|sort|ordered|order|ranked|rank|arranged|grouped|group) by(?: \w+)?|alphabetically|chronologically|"
                             r"in (?:alphabetical|chronological|reverse|descending|ascending) order|by (?:name|date|size|severity|priority|frequency|count)|"
                             r"(?:newest|oldest|largest|smallest|biggest|longest|shortest|latest|earliest|highest|lowest|fastest|slowest|most \w+|least \w+) first|"
                             r"відсортован\w+ за(?: \w+)?|впорядкован\w+ за(?: \w+)?|за алфавітом|за абеткою|за датою|за розміром|за пріоритетом|за спаданням|за зростанням|у порядку \w+"), I)),
    ("requirement", re.compile(_w(r"with (?:line numbers|sources|citations|examples|evidence|links|timestamps|references|reasons|context)|cite (?:the )?(?:source|sources|path|line)s?|"
                                r"including (?:the )?\w+|verbatim|word for word|з (?:посиланнями|прикладами|цитатами|номерами рядків|джерелами)|дослівно|із зазначенням \w+"), I)),
]
INLINE_STOP_RE = re.compile(r"[,;:()]")
INLINE_COORD_STOP_RE = re.compile(r"\s+(?:and|or|but|та|і|й|або|але)\s+", I)   # output-shape phrases end at a coordination ("in one sentence and the details")
CARD_NUMBER_RE = re.compile(_w(r"\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|thirty|fifty|hundred|few|several|dozen|"
                               r"одного|один|одну|два|двох|дві|три|трьох|чотири|чотирьох|п'ять|п’ять|п'яти|п’яти|десять|десяти|п'ятнадцяти|п’ятнадцяти|двадцять|двадцяти|тридцяти|сто|ста|кількох"), I)
LEADING_CONSTRAINT_KINDS = ("format", "locale", "cardinality", "ordering", "scope_only")   # "In one sentence, is the deploy safe?" / "Only compare …"
LEADING_SEP_RE = re.compile(r"\s*[,:—–-]\s+|\s+")
# words that never count as the head of a target ("the" alone is not a target): articles, quantifiers, possessives,
# prepositions. Demonstratives and pronouns ("this", "це", "it") *can* head a target ("Translate this into English").
ARTICLE_RE = re.compile(r"^(?:the|a|an|all|any|each|every|some|my|our|your|its|their|his|her|of|for|to|in|on|at|by|with|from|"
                        r"всі|усі|кожен|кожна|кожне|мій|моя|наш|наша|ваш|ваша|їх|його|її|у|в|на|з|із|до|для|про)$", I)

# --- pronouns / demonstratives --------------------------------------------------------------------------------------
PRONOUN_HEAD_RE = re.compile(rf"^\s*(?:(?:it|them|this|that|these|those|him|her|its|their|the same|the former|the latter|the above|the previous|the following|the below|"
                             rf"(?:each|both|all|none|neither|either)(?! (?!of\b)[^\W\d_])|all of them|"
                             rf"the (?:code|text|snippet|json|yaml|block|output|log|quote|excerpt) (?:below|above)|the \w+ (?:above|below|mentioned|mentioned earlier|from before|earlier))"
                             rf"(?:\s+(?:one|ones|file|files|thing|item|items|part|parts|section|sections|code|output|result|results|archive|document|list|table|"
                             rf"snippet|json|yaml|text|block|log|error|message|quote|line|lines|excerpt|example|config|script|function|query|command))?|"
                             rf"(?:цей|ця|це|ці|той|та|те|ті|його|її|їх|них|цього|цієї|цих|тих|ними|ним|нею|ньому|те саме|той самий|такий|таке)"
                             rf"(?:\s+(?:файл|файли|архів|документ|список|таблицю|код|результат|частину|розділ|фрагмент))?){E}", I)
PRONOUN_ANY_RE = re.compile(rf"{W}(?:it|them|they|these|those|its|their|the same|the latter|the former|его|його|її|їх|них|ними|ним|нею|ньому|ними){E}", I)

# --- declarative context statements (no trigger; the user states background, not an intent) --------------------
DECLARATIVE_RE = re.compile(
    rf"^\s*(?:(?:the|a|an|this|that|these|those|my|our|your|its|their|there|here|it|we|i|he|she|they|some|most|all|one of|each of|in our|on our|at the|for the|"
    rf"\w+ (?:is|are|was|were|has|have|had|runs|run|uses|use|contains|contain|says|say|shows|show|includes|include|fails|failed|returns|returned|lists|listed))|"
    rf"(?:це|цей|ця|ці|той|у нас|в нас|наш|наша|наше|наші|мій|моя|моє|мої|тут|там|є|сервіс|система|файл|файли|додаток|застосунок|лог|логи|конфіг|сервер|проєкт|проект|код|тест|тести|\w+ (?:є|має|має бути|містить|показує|працює|повертає|падає|не працює)))\b", I)

# --- scripts ----------------------------------------------------------------------------------------------------
LATIN_RE = re.compile(r"[A-Za-z\u00c0-\u024f]")
CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
UKRAINIAN_RE = re.compile(r"[іїєґІЇЄҐ]|\b(?:який|яка|які|яке|скільки|хто|де|що|чи|та|будь ласка|потрібно|треба)\b", I)
RUSSIAN_ONLY_RE = re.compile(r"[ыэъёЫЭЪЁ]")
ANY_LETTER_RE = re.compile(r"[^\W\d_]", re.U)
EN_FUNCTION_RE = re.compile(r"\b(?:the|a|an|and|is|are|to|of|in|please|do|not|what|which|how|list|show|it|this|that|for|with|me|all|any)\b", I)

# --- abbreviations that do not end a sentence -----------------------------------------------------------------------
ABBREV_RE = re.compile(r"(?:\b(?:e\.g|i\.e|etc|vs|cf|approx|no|dr|mr|mrs|ms|fig|eq|inc|ltd|st|напр|т\.д|т\.п|див|тис|грн|ст|рис|табл)|\b[A-Za-zА-Яа-яІіЇїЄєҐґ])\.$", I)
# "1." / "a." / "iv." at the start of a line is a list marker, not a sentence end
LIST_MARKER_BEFORE_DOT_RE = re.compile(r"(?:^|\n)[ \t]*\(?(?:\d{1,2}|[a-z]|[ivx]{1,4})$", I)

# --- nominal requests ("I need a summary of …") ------------------------------------------------------------------
NOMINAL_RE = re.compile(
    rf"^\s*(?:(?:give me|get me|can i get|can i have|i need|i want|i'd like|i would like|i am looking for|i'm looking for|looking for|"
    rf"дай|дайте|надай|надайте|мені потрібен|мені потрібна|мені потрібно|мені треба|хочу)\s+)?(?:(?:only|just|лише|тільки)\s+)?"
    # an article may be followed by up to three modifiers ("a detailed remediation plan", "a fix proposal"); without an article the noun must come first
    rf"(?P<np>(?:(?:a|an|the|some|another|one more|a second)\s+(?:(?:top|first|best|last)\s+)?(?:\d+\s+)?(?:(?!(?:is|are|was|were)\b)[\w'’-]+\s+){{0,3}}?|(?:якийсь|якась|якесь|коротке|короткий|стислий|стисле|детальний|детальну|детальне|окремий|окрему|ще один|ще одну|топ-?\d+)\s+)?"
    rf"(?P<noun>summary|overview|tl;?dr|recap|list|listing|enumeration|comparison|explanation|description|count|number|recommendation|recommendations|"
    rf"advice|suggestion|suggestions|translation|assessment|evaluation|breakdown|table|analysis|review|audit|check|verification|report|estimate|"
    rf"plan|proposal|draft|checklist|outline|diagram|chart|template|runbook|example|examples|matrix|timeline|write-?up|spec|specification|preview|diff preview|patch preview|"
    rf"підсумок|резюме|огляд|перелік|список|порівняння|пояснення|опис|кількість|рекомендація|рекомендації|порада|поради|переклад|оцінка|аналіз|перевірка|звіт|"
    rf"план|пропозиція|пропозицію|чернетка|чернетку|чеклист|схема|схему|таблиця|таблицю|шаблон|приклад|приклади)"
    rf"{E})(?!\s+(?:is|are|was|were|has|have|had|does|do|did|will|would|should|must|can|could|looks?|seems?|says?|shows?|є|має|буде|виглядає|каже)\b)\s*(?:of|for|on|about|щодо|про|для|по)?\s*", I)
NOMINAL_ACTION = {
    "summary": "summarize", "overview": "summarize", "tldr": "summarize", "tl;dr": "summarize", "recap": "summarize", "підсумок": "summarize",
    "резюме": "summarize", "огляд": "summarize",
    "list": "enumerate", "listing": "enumerate", "enumeration": "enumerate", "перелік": "enumerate", "список": "enumerate",
    "comparison": "compare", "порівняння": "compare",
    "explanation": "explain", "пояснення": "explain",
    "description": "describe", "опис": "describe",
    "report": "report", "звіт": "report", "assessment": "assess", "оцінка": "assess", "estimate": "compute", "translation": "translate", "переклад": "translate",
    "count": "count", "number": "count", "кількість": "count",
    "recommendation": "recommend", "recommendations": "recommend", "advice": "recommend", "suggestion": "recommend", "suggestions": "recommend",
    "рекомендація": "recommend", "рекомендації": "recommend", "порада": "recommend", "поради": "recommend",
    "translation": "translate", "переклад": "translate",
    "assessment": "assess", "evaluation": "assess", "оцінка": "assess",
    "audit": "verify", "verification": "verify", "перевірка": "verify",
    # deliverables that live in the answer → compose (an artefact in the reply, never a file)
    "plan": "compose", "proposal": "compose", "draft": "compose", "checklist": "compose", "outline": "compose", "diagram": "compose", "chart": "compose",
    "template": "compose", "runbook": "compose", "example": "compose", "examples": "compose", "matrix": "compose", "timeline": "compose", "write-up": "compose",
    "writeup": "compose", "spec": "compose", "specification": "compose", "table": "compose", "preview": "compose", "diff preview": "compose", "patch preview": "compose",
    "план": "compose", "пропозиція": "compose", "пропозицію": "compose", "чернетка": "compose", "чернетку": "compose", "чеклист": "compose", "схема": "compose",
    "схему": "compose", "таблиця": "compose", "таблицю": "compose", "шаблон": "compose", "приклад": "compose", "приклади": "compose",
}   # nouns absent from this map (review, analysis, breakdown, check, аналіз) are ambiguous → no objective

# --- action triggers (priority order) -------------------------------------------------------------------------------
# Each entry: (action, family, pattern). Family ∈ imperative | interrogative. Interrogative patterns keep the
# wh-word in the target (zero-width lookahead) so the target text stays a readable question.
_NUM = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
ACTION_RULES: list[tuple[str, str, re.Pattern[str]]] = [
    # specific multi-word forms first
    ("count", "interrogative", re.compile(rf"^\s*(?:how many|how much|what(?:'s| is) the (?:number|count|total) of|number of|скільки|яка кількість|скільки всього)\s+", I)),
    ("enumerate", "imperative", re.compile(_w(r"list(?: out| me)?|enumerate|itemi[sz]e|name all|name every|name|(?:give|show|make|provide|produce|write|send) (?:me )?(?:a |an |the |all )?(?:full |complete |short )?(?:list|listing|enumeration) of|"
                                              r"переліч(?:и|іть)?|перелічити|перерахуй(?:те)?|перерахувати|(?:наведи|наведіть|виведи|виведіть|склади|складіть|зроби|зробіть|дай|дайте) (?:повний |короткий )?(?:список|перелік)(?: усіх| всіх)?|назви (?:всі|усі)|назвіть (?:всі|усі)") + r"\s*", I)),
    ("compare", "imperative", re.compile(_w(r"compare|contrast|diff|differentiate|cross-check|reconcile|"
                                            r"порівняй(?:те)?|порівняти|зістав(?:те)?|зіставити|звір(?:и|те)?|звірити") + r"\s*", I)),
    ("compare", "interrogative", re.compile(rf"^\s*(?=(?:what (?:is|are) the differences?|how (?:does|do|did) \S+(?: \S+){{0,5}} differ|what differs|what changed|"
                                            rf"у чому (?:різниця|відмінність|відмінності)|чим (?:відрізняється|відрізняються|різняться))\b)", I)),
    ("enumerate", "interrogative", re.compile(rf"^\s*(?=(?:what are (?:all )?(?:the|its|their|our|my)|which (?:\w+ )?(?:are there|exist|are available|are present|are open|are configured)|які (?:є|існують|наявні|налаштовані))\b)", I)),
    ("analyze", "imperative", re.compile(_w(r"analy[sz]e|проаналізуй(?:те)?|проаналізувати|розбери(?:те)?|розібрати") + r"\s*", I)),
    ("summarize", "imperative", re.compile(_w(r"summari[sz]e|sum up|recap|condense|brief me on|(?:give|write|provide|send|prepare|make|do) (?:me |us )?(?:a |an )?(?:brief |short |quick |one-line |high-level |concise )?(?:summary|overview|recap|tl;?dr)(?: of)?|tl;?dr|"
                                              r"зроби (?:короткий |короткe |стислий |стисле )?(?:summary|підсумок|резюме|огляд)|"
                                              r"підсумуй(?:те)?|підсумувати|узагальни(?:ти)?|узагальніть|резюмуй(?:те)?|резюмувати|стисло (?:виклади|викладіть|опиши|опишіть|перекажи)|коротко (?:опиши|опишіть|розкажи|розкажіть|перекажи)") + r"\s*", I)),
    ("describe", "imperative", re.compile(_w(r"describe|characteri[sz]e|tell me about|walk me through|give (?:me )?(?:a |an )?(?:description|overview) of|outline|"
                                             r"опиши|опишіть|описати|охарактеризуй(?:те)?|розкажи (?:мені )?про|розкажіть (?:мені )?про") + r"\s*", I)),
    ("explain", "imperative", re.compile(_w(r"explain|clarify|elaborate on|justify|interpret|поясни|поясніть|пояснити|роз'ясни|роз’ясни|розтлумач(?:те)?|обґрунтуй(?:те)?") + r"\s*", I)),
    ("explain", "interrogative", re.compile(rf"^\s*(?=(?:why\b|how (?:does|do|did|is|are|can|could|would|should)\b|what does \S+(?: \S+){{0,4}} mean|чому\b|як (?:працює|працюють|саме|це)\b|що означає\b))", I)),
    ("recommend", "imperative", re.compile(_w(r"recommend|suggest|propose|advise|порадь(?:те)?|порадити|порекомендуй(?:те)?|порекомендувати|запропонуй(?:те)?|запропонувати|пропонуй(?:те)?|пропонувати|рекомендуй(?:те)?") + r"\s*", I)),
    ("recommend", "interrogative", re.compile(rf"^\s*(?=(?:what should (?:i|we)|what (?:are|is) (?:the )?(?:next steps?|best (?:way|option|approach))|how (?:can|could|should) (?:i|we) improve|"
                                              rf"що (?:мені|нам) (?:робити|зробити|варто)|які (?:наступні кроки|рекомендації)|що порадиш|що порадите)\b)", I)),
    ("verify", "imperative", re.compile(_w(r"verify|validate|confirm|double[- ]check|check (?:that|whether|if)|make sure (?:that)?|ensure (?:that)?|test (?:whether|if|that)|"
                                           r"перевір(?:те)?,? чи|перевір(?:те)?,? що|перевір(?:те)?|перевірити|підтвердь(?:те)?,? що|підтверди(?:ти)?,? що|підтвердь(?:те)?|підтверди(?:ти)?|підтвердіть|"
                                           r"переконайся|переконайтеся|валідуй") + r"\s*", I)),
    ("choose", "imperative", re.compile(_w(r"choose|pick|select|decide on|decide between|decide(?=\s+which\b)|обери|оберіть|обрати|вибери|виберіть|вибрати|виріши(?:ти)?(?=,?\s+(?:який|яка|яке|які|котрий)\b)") + r"\s*", I)),
    ("prioritize", "imperative", re.compile(_w(r"prioriti[sz]e|rank|triage|пріоритизуй(?:те)?|пріоритизувати|ранжуй(?:те)?|ранжувати|розстав(?:те)? пріоритети") + r"\s*", I)),
    ("flag", "imperative", re.compile(_w(r"flag|highlight|mark|call out|познач(?:те)?|позначити|виділи(?:ти)?|виділіть|відміть|відмітьте") + r"\s*", I)),
    ("clarify", "imperative", re.compile(_w(r"ask(?= (?:me )?(?:(?:clarifying |follow-up |any )?questions?|for clarification|if (?:anything|something) is unclear|before|first))|уточни(?:ти)?|уточніть|запитай(?:те)?|постав(?:те)?(?= (?:питання|запитання))") + r"\s*", I)),
    ("assess", "imperative", re.compile(_w(r"assess|evaluate|judge|rate|(?:determine|decide|say|tell(?: me)?|state|indicate|report|note|find out|figure out|estimate|check|see|work out)(?=\s+(?:whether|if)\b)|"
                                           r"оціни(?:ти)?|оцініть|(?:визнач|визначте|скажи|скажіть|повідом|повідомте|з'ясуй|з’ясуй|з'ясуйте|з’ясуйте)(?=,?\s+чи\b)") + r"\s*", I)),
    ("assess", "interrogative", re.compile(rf"^\s*(?=(?:is|are|was|were|does|do|did|can|could|should|would|will|has|have|had|am|isn'?t|aren'?t|doesn'?t|don'?t|didn'?t|чи)\b)", I)),
    ("identify", "imperative", re.compile(_w(r"identify|pinpoint|point out|specify|(?:determine|decide|say|tell(?: me)?|state|indicate|name|report|note|find out|figure out|work out|see|check|show(?: me)?)(?=\s+(?:which|what|who|whom|whose|where|when|how)\b)|"
                                             r"визнач(?:те)?|визначити|вкажи|вкажіть|вказати|назви|назвіть|назвати|"
                                             # "скажи, що все гаразд" (comma + що = *that*) is report; "скажи що не так" (що = *what*) is identify
                                             r"(?:скажи|скажіть|повідом|повідомте|з'ясуй|з’ясуй|з'ясуйте|з’ясуйте|покажи|покажіть)(?=,?\s+(?:які|який|яка|яке|хто|де|коли|котрий|котрі|скільки)\b|\s+що\b)") + r"\s*", I)),
    ("explain", "interrogative", re.compile(rf"^\s*(?=what (?:does|do|did|is|are|was|were) [^,;?]{{1,80}}?\b(?:mean|means|meant|signif(?:y|ies)|stand for|stands for)\b)", I)),
    ("identify", "interrogative", re.compile(rf"^\s*(?=(?:which|what|who|whom|whose|where|when|який|яка|яке|які|хто|що|де|коли|котрий|котра|котре|котрі)\b)", I)),
    ("report", "imperative", re.compile(_w(r"report|tell me|tell us|say|state|let me know|повідом(?:те)?|повідомити|доповіси|доповідай|звітуй(?:те)?|скажи|скажіть|дай знати") + r"\s*", I)),
    ("locate", "imperative", re.compile(_w(r"find(?! out)|locate|search(?: for)?|look (?:for|up)|grep(?: for)?|look through \S+ for|знайди|знайдіть|знайти|пошукай|пошукайте|відшукай|відшукайте|відшукати") + r"\s*", I)),
    ("extract", "imperative", re.compile(_w(r"extract|pull(?: out)?|quote|cite|retrieve|get(?: me)?|give(?: me| us)?|provide|supply|share|fetch|read out|print(?: out)?|output|return|collect|gather|attach|"
                                            r"витягни|витягніть|витягнути|процитуй(?:те)?|процитувати|наведи цитату|дістань|дістаньте|отримай|отримайте|збери|зберіть|зібрати|додай цитати") + r"\s*", I)),
    ("inspect", "imperative", re.compile(_w(r"inspect|review|examine|audit|look at|look into|look through|go through|read through|read|check|scan|study|"
                                            r"переглянь(?:те)?|переглянути|подивись|подивися|подивіться|розглянь(?:те)?|розглянути|прочитай|прочитайте|прочитати|оглянь(?:те)?|вивчи(?:ти)?|вивчіть|продивись|продивіться") + r"\s*", I)),
    ("show", "imperative", re.compile(_w(r"show(?: me)?|display|present|reveal|open|view|see|"
                                         r"покажи|покажіть|показати|відобрази|відобразіть|продемонструй(?:те)?|відкрий|відкрийте") + r"\s*", I)),
    ("count", "imperative", re.compile(_w(r"count(?: up)?|tally|(?:tell me|say|determine|work out|find out|скажи|скажіть|повідом|визнач),?(?=\s+(?:how many|how much|скільки)\b)|"
                                          r"порахуй(?:те)?|порахувати|полічи(?:ти)?|полічіть|підрахуй(?:те)?|підрахувати") + r"\s*", I)),
    ("compute", "imperative", re.compile(_w(r"calculate|compute|estimate|sum(?: up)?|add up|average|total|measure|обчисли(?:ти)?|обчисліть|розрахуй(?:те)?|розрахувати|виміряй(?:те)?") + r"\s*", I)),
    ("classify", "imperative", re.compile(_w(r"classify|categori[sz]e|label|tag|group|bucket|класифікуй(?:те)?|класифікувати|категоризуй(?:те)?|згрупуй(?:те)?") + r"\s*", I)),
    ("translate", "imperative", re.compile(_w(r"translate|переклади|перекладіть|перекласти") + r"\s*", I)),
    ("transform", "imperative", re.compile(_w(r"convert|reformat|format|render|rewrite|rephrase|reword|paraphrase|transform|normali[sz]e|sort|tabulate|turn|reorganize|restructure|parse|break (?:down|up)|split(?: up)?|decompose|"
                                              r"перетвори(?:ти)?|перетворіть|конвертуй(?:те)?|конвертувати|відформатуй(?:те)?|перепиши|перепишіть|переписати|перефразуй(?:те)?|відсортуй(?:те)?|відсортувати|розбий(?:те)?|розбити|поділи(?:ти)?|поділіть|розклади(?:ти)?|розкладіть|декомпозуй(?:те)?") + r"\s*", I)),
    # an artefact *in the answer* (table, example, plan, note…) — inform, not mutate; must precede create/modify
    # "write READY" / "напиши 'OK' у відповіді" — a literal token written in the answer is composed, not created
    ("compose", "imperative", re.compile(_w(r"(?:write|print|put|say|reply with|respond with|answer with|output|напиши|напишіть|виведи|виведіть|відповідай|відповідь)(?: me| us| мені| нам)?"
                                            r"(?: (?:just|only|simply|exactly|the word|the single word|the literal|the token|лише|тільки|просто|слово))?") + r"(?=" + LITERAL_TOKEN_RE.pattern.lstrip("^") + r")\s*", I | re.U)),
    ("compose", "imperative", re.compile(_w(r"draft|write[- ]up|write down|note down|jot down|sketch out|накидай|накидайте|начерни|запиши коротко|викладіть|виклади") + r"(?: me| us| мені| нам)?\s*", I)),
    ("compose", "imperative", re.compile(_w(r"(?:make|create|build|write|generate|draft|produce|prepare|compose|put together|склади|складіть|створи|створіть|напиши|напишіть|підготуй|підготуйте|зроби|зробіть|сформуй|сформуйте)(?: me| us| мені| нам)?"
                                            r"(?=(?: (?:a|an|the|some|one|two|three|\d+))?(?: (?!(?:file|files|branch|directory|folder|script|repo|repository|service|container|user|account|"
                                            r"and|or|then|but|with|for|in|on|to|from|of|at|into|that|which|it|them|me|us)\b)[\w'’-]+){0,3}?"
                                            r" (?:table|list|summary|report|diagram|chart|example|examples|outline|plan|checklist|matrix|snippet|note|notes|doc|documentation|overview|comparison|"
                                            r"timeline|runbook|release notes?|changelog|draft|proposal|brief|write-?up|readme|guide|tutorial|faq|glossary|body|payload|template|mock|sample|sketch|"
                                            r"description|message|announcement|email|reply|response|answer|paragraph|title|caption|abstract|explanation|statement|statements|spec|specification|rfc|adr|agenda|prompt|query|queries|regex|"
                                            r"diff|commands?|instructions|steps|snippets|sql|cheat ?sheet|"
                                            r"опис|повідомлення|відповідь|заголовок|пояснення|специфікацію|запит|анонс|лист|"
                                            r"таблицю|список|звіт|приклад|приклади|план|схему|нотатку|чеклист|огляд|конспект|інструкцію|документацію|порівняння|перелік)\b"
                                            # "create a table in the database" / "write a message to the queue" persist something → not an answer artefact
                                            r"(?!\s+(?:in|inside|within|on|into|to)\s+(?:the\s+|a\s+|an\s+|our\s+|my\s+)?(?:database|db|schema|repo|repository|cluster|namespace|bucket|disk|server|filesystem|folder|directory|branch|table|queue|topic)\b))") + r"\s*", I)),
    ("create", "imperative", re.compile(_w(r"make (?:a|an|me|some|new|the)(?=\s)|create|write|generate|draft|compose|build|design|implement|add|produce|prepare|set up|save|store|persist|"
                                           r"створи(?:ти)?|створіть|напиши|напишіть|написати|згенеруй(?:те)?|згенерувати|склади|складіть|скласти|побудуй(?:те)?|реалізуй(?:те)?|додай|додайте|додати|підготуй(?:те)?|підготувати|"
                                           r"збережи|збережіть|зберегти|зберігай(?:те)?") + r"\s*", I)),
    ("modify", "imperative", re.compile(_w(r"make|change|modify|edit|update|fix|repair|improve|optimi[sz]e|speed up|refactor|rename|replace|adjust|tune|increase|decrease|reduce|set|configure|enable|disable|upgrade|migrate|patch|correct|touch|alter|"
                                           r"внес(?:и|іть|ти) (?:зміни|правки|виправлення)|внос(?:ь|ьте|ити) (?:зміни|правки|виправлення)|зміни(?:ти)?|змініть|змінюй(?:те)?|редагуй(?:те)?|виправ(?:те)?|виправити|полагодь|полагодьте|покращ(?:и|іть)?|покращити|оптимізуй(?:те)?|оптимізувати|прискор(?:те)?|прискорити|пришвидш(?:и|іть)?|пришвидшити|перейменуй(?:те)?|заміни(?:ти)?|замініть|налаштуй(?:те)?|налаштувати|увімкни|увімкніть|вимкни|вимкніть|онови(?:ти)?|оновіть|зроби|зробіть|зробити|чіпай(?:те)?|чіпати|торкайся|торкайтеся|торкатися") + r"\s*", I)),
    ("run", "imperative", re.compile(_w(r"run|execute|launch|start|restart|stop|kill|deploy|install|uninstall|trigger|invoke|call|apply|roll back|rollback|follow(?: the| these| those| its| their)?(?: instructions?| steps| them| it)?|obey|comply with|do what|perform|send|email|post|publish|upload|download|"
                                        r"connect(?: to| into)?|ssh(?: into| to| in)?|log ?in(?: to| into)?|sign in(?: to| into)?|ping|curl|telnet(?: to)?|dial|"
                                        r"запусти(?:ти)?|запустіть|запускай(?:те)?|виконай(?:те)?|виконати|виконуй(?:те)?|розгорни(?:ти)?|розгорніть|встанови(?:ти)?|встановіть|встановлюй(?:те)?|інсталюй(?:те)?|"
                                        r"перезапусти(?:ти)?|перезапускай(?:те)?|зупини(?:ти)?|зупиніть|дотримуйся|дотримуйтеся|слідуй|слідуйте|надішли|надішліть|відправ(?:те)?|опублікуй(?:те)?|завантаж(?:те)?|"
                                        r"підключайся|підключайтеся|підключатися|підключись|під'єднуйся|під’єднуйся|під'єднуйтеся|під’єднуйтеся|заходь(?:те)? на|логінься|логіньтеся") + r"\s*", I)),
    ("remove", "imperative", re.compile(_w(r"delete|remove|drop|erase|purge|clean up|clear|wipe|revoke|strip|видали(?:ти)?|видаліть|видаляй(?:те)?|вилучи(?:ти)?|вилучіть|очисти(?:ти)?|очистіть|зітри|зітріть|прибери|приберіть") + r"\s*", I)),
]

# imperative-only starts, used as the lookahead for coordination splits (wh-words excluded so ", which are public"
# never splits); built from the imperative rules plus negation/exclusion/requirement starts.
_IMPERATIVE_HEADS = [p.pattern for a, fam, p in ACTION_RULES if fam == "imperative"]
IMPERATIVE_LOOKAHEAD_RE = re.compile(r"(?=" + "|".join(f"(?:{h})" for h in _IMPERATIVE_HEADS) + r"|" + PROHIBITION_START_RE.pattern.lstrip("^") + r"|" +
                                     EXCLUSION_START_RE.pattern.lstrip("^") + r"|" + REQUIREMENT_START_RE.pattern.lstrip("^") + r"|\s*" + NO_NOUN_HEAD_RE.pattern +
                                     r"|\s*(?:only|just|simply|тільки|лише|просто|you (?:may|can|could|might|should)(?: also| still)?|feel free to|можеш|можете|можна)\s+(?:" +
                                     "|".join(f"(?:{h})" for h in _IMPERATIVE_HEADS) + r")" +
                                     r"|" + NULL_OBJECT_CLAUSE_RE.pattern.lstrip("^") + r"|" + ELSE_START_RE.pattern.lstrip("^") + r")", I)
# interrogative heads for "and how many …" / "та скільки …" coordination
INTERROGATIVE_LOOKAHEAD_RE = re.compile(r"(?=" + "|".join(f"(?:{p.pattern.lstrip('^')})" for a, fam, p in ACTION_RULES if fam == "interrogative") + r")", I)


def lang_of(text: str) -> str:
    return "uk" if CYRILLIC_RE.search(text) else "en"
